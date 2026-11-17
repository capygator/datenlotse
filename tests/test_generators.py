"""M4: Sichten, Renderer (Mermaid, Archify) und Generatoren (ODCS, TMDL).

Snapshots liegen unter ``tests/snapshots/nordwind/``. Neu erzeugen mit
``LOTSE_UPDATE_SNAPSHOTS=1 uv run pytest tests/test_generators.py``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import NORDWIND, Files, write_workspace
from typer.testing import CliRunner

from lotse.cli import app
from lotse.gen import odcs, tmdl
from lotse.render import archify
from lotse.store.build import build
from lotse.views import get_view, list_views, run_view

runner = CliRunner()
SNAPSHOTS = Path(__file__).parent / "snapshots" / "nordwind"
UPDATE = os.environ.get("LOTSE_UPDATE_SNAPSHOTS") == "1"
VIEWS = ("lineage", "lineage_detail", "model")


def _invoke(*args: str) -> None:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output


def _generate_all(ws: Path, out: Path) -> None:
    for view in VIEWS:
        _invoke("render", "mermaid", "--view", view, "-w", str(ws), "-o", str(out / "render"))
        _invoke("render", "archify", "--view", view, "-w", str(ws), "-o", str(out / "render"))
    _invoke("gen", "odcs", "-w", str(ws), "-o", str(out))
    _invoke("gen", "tmdl", "-w", str(ws), "-o", str(out))


def _tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def nordwind_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("m4")
    ws = base / "nordwind"
    shutil.copytree(NORDWIND, ws, ignore=shutil.ignore_patterns(".lotse", "out"))
    out = base / "gen"
    _generate_all(ws, out)
    return out


# --- Snapshots und Idempotenz ---------------------------------------------------------------


@pytest.mark.parametrize("part", ["render", "odcs", "tmdl"])
def test_snapshot(nordwind_out: Path, part: str) -> None:
    actual = _tree(nordwind_out / part)
    target = SNAPSHOTS / part
    if UPDATE:
        shutil.rmtree(target, ignore_errors=True)
        for rel, data in actual.items():
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            (target / rel).write_bytes(data)
    expected = _tree(target)
    assert sorted(actual) == sorted(expected)
    for rel in actual:
        assert actual[rel] == expected[rel], f"Snapshot weicht ab: {part}/{rel}"


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    ws = tmp_path / "nordwind"
    shutil.copytree(NORDWIND, ws, ignore=shutil.ignore_patterns(".lotse", "out"))
    _generate_all(ws, tmp_path / "a")
    _generate_all(ws, tmp_path / "b")
    first, second = _tree(tmp_path / "a"), _tree(tmp_path / "b")
    assert first == second
    assert len(first) > 20


def test_outputs_are_lf_utf8_without_local_paths(nordwind_out: Path) -> None:
    for rel, data in _tree(nordwind_out).items():
        text = data.decode("utf-8")
        assert "\r" not in text, rel
        assert str(nordwind_out.parent) not in text, rel


def test_default_output_is_workspace_out(tmp_path: Path) -> None:
    ws = tmp_path / "nordwind"
    shutil.copytree(NORDWIND, ws, ignore=shutil.ignore_patterns(".lotse", "out"))
    _invoke("render", "mermaid", "--view", "lineage", "-w", str(ws))
    _invoke("gen", "odcs", "-w", str(ws))
    assert (ws / "out" / "lineage.mmd").is_file()
    assert (ws / "out" / "odcs" / "auftragsbestand-cockpit.odcs.yaml").is_file()


def test_generator_replaces_only_own_files(tmp_path: Path) -> None:
    ws = tmp_path / "nordwind"
    shutil.copytree(NORDWIND, ws, ignore=shutil.ignore_patterns(".lotse", "out"))
    stale = ws / "out" / "tmdl" / "auftragsbestand-cockpit" / "alt.tmdl"
    stale.parent.mkdir(parents=True)
    stale.write_text("alt")
    foreign = ws / "out" / "tmdl" / "handgepflegt.txt"
    foreign.write_text("bleibt")
    old_contract = ws / "out" / "odcs" / "entfernt.odcs.yaml"
    old_contract.parent.mkdir(parents=True)
    old_contract.write_text("alt")
    _invoke("gen", "tmdl", "-w", str(ws))
    _invoke("gen", "odcs", "-w", str(ws))
    assert not stale.exists()
    assert not old_contract.exists()
    assert foreign.read_text() == "bleibt"


# --- Sichten ---------------------------------------------------------------------------------


def test_views_are_registered() -> None:
    names = {v.name: v.kind for v in list_views()}
    assert names == {"lineage": "flow", "lineage_detail": "flow", "model": "erd"}


def test_lineage_aggregates_to_core_nodes() -> None:
    result = run_view(build(NORDWIND).db_path, get_view("lineage"))
    assert 8 <= len(result.nodes) <= 12
    assert [label for _, label in result.lanes()] == [
        "Quelle",
        "Tabelle",
        "Kennzahl",
        "Datenprodukt",
        "Entscheidung",
    ]
    blocks = {n.id: n for n in result.nodes if n.id.startswith("block.")}
    assert blocks["block.vertrieb-leitung"].detail == [
        "measure.auftragseingang",
        "measure.liefertreue",
    ]
    assert blocks["block.vertrieb-leitung"].status == "draft"
    gap = next(n for n in result.nodes if n.id == "table.fact_lieferzusage")
    assert gap.finding == "gap"


def test_model_view_resolves_reference_target_column() -> None:
    result = run_view(build(NORDWIND).db_path, get_view("model"))
    assert len(result.nodes) == 9
    edge = next(e for e in result.edges if e.src == "table.fact_kapazitaet" and e.label == "monat")
    assert edge.dst == "table.dim_datum"
    assert edge.detail == {"from_column": "monat", "to_column": "datum"}
    dim_datum = next(n for n in result.nodes if n.id == "table.dim_datum")
    assert [c["name"] for c in dim_datum.detail] == ["datum", "monat", "quartal", "jahr"]


def test_unknown_view_fails(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["render", "mermaid", "--view", "gibtsnicht", "-w", str(NORDWIND), "-o", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "Unbekannte Sicht" in result.output


# --- Archify ---------------------------------------------------------------------------------


@pytest.mark.parametrize("view", VIEWS)
def test_archify_output_matches_vendored_schema(nordwind_out: Path, view: str) -> None:
    doc = json.loads((nordwind_out / "render" / f"{view}.json").read_text(encoding="utf-8"))
    assert archify.validate(doc) == []
    expected = "erd" if view == "model" else "dataflow"
    assert doc["diagram_type"] == expected


def test_archify_schema_rejects_invalid_document() -> None:
    doc = {"schema_version": 1, "diagram_type": "dataflow", "meta": {"title": "x"}}
    assert archify.validate(doc)


# --- ODCS ------------------------------------------------------------------------------------


def _contract(nordwind_out: Path) -> dict[str, Any]:
    text = (nordwind_out / "odcs" / "auftragsbestand-cockpit.odcs.yaml").read_text("utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    return data


def test_odcs_validates_against_official_schema(nordwind_out: Path) -> None:
    contract = _contract(nordwind_out)
    assert odcs.validate(contract) == []
    assert contract["apiVersion"] == "v3.1.0"


def test_odcs_schema_is_vendored_tag_file() -> None:
    from importlib import resources

    schema = json.loads(
        resources.files("lotse.gen.schemas").joinpath(odcs.SCHEMA_FILE).read_text("utf-8")
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2019-09/schema"
    assert schema["$defs"]["StableId"]["pattern"] == "^[A-Za-z0-9_-]+$"


def test_odcs_rejects_invalid_contract(nordwind_out: Path) -> None:
    contract = _contract(nordwind_out)
    contract["schema"][0]["quality"] = [{"name": "x", "rule": "not_negative"}]
    del contract["kind"]
    errors = odcs.validate(contract)
    assert any("kind" in e for e in errors)
    assert any("quality" in e for e in errors)


def test_odcs_maps_tables_measures_and_owner(nordwind_out: Path) -> None:
    contract = _contract(nordwind_out)
    names = [o["name"] for o in contract["schema"]]
    assert names == sorted(names) and "fact_auftragsposition" in names and "dim_datum" in names
    fact = next(o for o in contract["schema"] if o["name"] == "fact_auftragsposition")
    kunde = next(p for p in fact["properties"] if p["name"] == "kunde_id")
    assert kunde["relationships"] == [{"type": "foreignKey", "to": "dim_kunde.kunde_id"}]
    assert {q["name"] for q in fact["quality"]} == {"not_negative"}
    measures = next(c["value"] for c in contract["customProperties"] if c["property"] == "measures")
    assert [m["name"] for m in measures][:2] == ["Auftragsbestand", "Auftragseingang"]
    owner = contract["team"]["members"][0]
    assert owner["username"] == "controlling-leitung"
    assert owner["role"].startswith("Produkt-Owner")
    assert "fact_lieferzusage" in contract["description"]["limitations"]


# --- TMDL ------------------------------------------------------------------------------------

MODEL_DIR = "auftragsbestand-cockpit/auftragsbestand-cockpit.SemanticModel/definition"


def test_tmdl_project_structure(nordwind_out: Path) -> None:
    root = nordwind_out / "tmdl" / "auftragsbestand-cockpit"
    pbip = json.loads((root / "auftragsbestand-cockpit.pbip").read_text("utf-8"))
    assert pbip["artifacts"] == [{"report": {"path": "auftragsbestand-cockpit.Report"}}]
    pbir = json.loads(
        (root / "auftragsbestand-cockpit.Report" / "definition.pbir").read_text("utf-8")
    )
    assert pbir["datasetReference"]["byPath"]["path"] == "../auftragsbestand-cockpit.SemanticModel"
    pbism = root / "auftragsbestand-cockpit.SemanticModel" / "definition.pbism"
    assert json.loads(pbism.read_text("utf-8"))["version"] == "4.2"


def test_tmdl_syntax_rules(nordwind_out: Path) -> None:
    definition = nordwind_out / "tmdl" / MODEL_DIR
    files = sorted(definition.rglob("*.tmdl"))
    assert {f.name for f in files} >= {"database.tmdl", "model.tmdl", "relationships.tmdl"}
    tags: list[str] = []
    for f in files:
        for line in f.read_text("utf-8").splitlines():
            assert not line.startswith(" "), f"{f.name}: Einrückung nur mit Tabs: {line!r}"
            match = re.match(r"\t+lineageTag: (.+)$", line)
            if match:
                tags.append(match.group(1))
    assert len(tags) == len(set(tags)), "lineageTags müssen eindeutig sein"
    uuid = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    assert all(uuid.match(t) for t in tags)

    model = (definition / "model.tmdl").read_text("utf-8")
    refs = re.findall(r"^ref table (.+)$", model, re.M)
    tables = {f.stem for f in (definition / "tables").glob("*.tmdl")}
    assert {r.strip("'") for r in refs} == tables


def test_tmdl_relationships_point_to_existing_columns(nordwind_out: Path) -> None:
    definition = nordwind_out / "tmdl" / MODEL_DIR
    columns: set[tuple[str, str]] = set()
    for f in (definition / "tables").glob("*.tmdl"):
        for col in re.findall(r"^\tcolumn (.+)$", f.read_text("utf-8"), re.M):
            columns.add((f.stem, col.strip("'")))
    rels = (definition / "relationships.tmdl").read_text("utf-8")
    ends = re.findall(r"^\t(?:from|to)Column: '?(.+?)'?\.(.+)$", rels, re.M)
    assert len(ends) == 26
    for table, col in ends:
        assert (table, col.strip("'")) in columns


def test_tmdl_measures_are_placeholders_with_definition(nordwind_out: Path) -> None:
    text = (nordwind_out / "tmdl" / MODEL_DIR / "tables" / "Fakt Auftragsposition.tmdl").read_text(
        "utf-8"
    )
    assert "\tmeasure Auftragsbestand = BLANK()\n" in text
    assert (
        "\t/// Definition (Leitung Vertrieb): Summe aller bestätigten, noch nicht gelieferten "
        "Auftragspositionen\n" in text
    )
    assert "\t\tformatString: #,##0 €\n" in text


def _variant(base: Files) -> Files:
    """Konflikt-Kennzahl mit zwei Definitionen und eine Kennzahl ohne Tabelle."""
    base["stakeholders/zwei.yaml"] = {"id": "stakeholder.zwei", "name": "Zwei"}
    base["measures/m.yaml"]["status"] = "conflict"
    base["measures/m.yaml"]["definitions"].append({"by": "stakeholder.zwei", "text": "Summe Y"})
    base["measures/n.yaml"] = {
        "id": "measure.n",
        "name": "N",
        "owner": "stakeholder.owner",
        "grain": ["dimension.k"],
        "serves": ["decision.d"],
    }
    base["products/p.yaml"]["measures"].append("measure.n")
    base["tables/t.yaml"]["columns"] = [{"name": "id", "key": True}, {"name": "wert"}]
    return base


def test_conflict_keeps_all_definitions(tmp_path: Path, base: Files) -> None:
    result = build(write_workspace(tmp_path / "ws", _variant(base)))
    files = odcs.generate(result)
    contract = yaml.safe_load(files["p.odcs.yaml"])
    assert odcs.validate(contract) == []
    measures = next(c["value"] for c in contract["customProperties"] if c["property"] == "measures")
    m = next(x for x in measures if x["id"] == "measure.m")
    assert [d["text"] for d in m["definitions"]] == ["Summe X", "Summe Y"]
    assert contract["status"] == "draft"

    model = tmdl.generate(result)
    table_t = model["p/p.SemanticModel/definition/tables/T.tmdl"]
    assert "/// Definition (Owner): Summe X" in table_t
    assert "/// Definition (Zwei): Summe Y" in table_t
    homeless = model["p/p.SemanticModel/definition/tables/Kennzahlen.tmdl"]
    assert "\tmeasure N = BLANK()" in homeless
    assert "partition Kennzahlen = calculated" in homeless


def test_measure_name_does_not_collide_with_column(tmp_path: Path, base: Files) -> None:
    base = _variant(base)
    base["measures/m.yaml"]["name"] = "wert"
    result = build(write_workspace(tmp_path / "ws", base))
    table_t = tmdl.generate(result)["p/p.SemanticModel/definition/tables/T.tmdl"]
    assert "\tmeasure 'wert (2)' = BLANK()" in table_t
    assert "\tcolumn wert\n" in table_t


def test_generators_refuse_workspace_with_errors(tmp_path: Path, base: Files) -> None:
    base["measures/m.yaml"]["from_tables"] = ["table.fehlt"]
    ws = write_workspace(tmp_path / "ws", base)
    result = runner.invoke(app, ["gen", "odcs", "-w", str(ws)])
    assert result.exit_code == 1
    assert not (ws / "out").exists()
