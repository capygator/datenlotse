"""M6: Backlog-Planung (Snapshot, Byte-Stabilität) und --apply gegen simuliertes ADO."""

from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path

import pytest
from ado_fake import ORG, PROJECT, SCRUM, FakeAdo
from conftest import BASE, NORDWIND, REPO, Files, write_workspace
from typer.testing import CliRunner

from lotse.cli import app
from lotse.gen.ado import rest
from lotse.gen.ado.plan import Backlog, plan_backlog
from lotse.gen.ado.rest import RestWorkItemStore
from lotse.gen.ado.sync import AdoError, Target, render_fields, sync, truncate_title
from lotse.store.build import build

SNAPSHOT = REPO / "tests" / "snapshots" / "ado" / "nordwind-backlog.json"
runner = CliRunner()


def _nordwind(tmp_path: Path) -> Path:
    target = tmp_path / "nordwind"
    shutil.copytree(NORDWIND, target, ignore=shutil.ignore_patterns(".lotse", "out"))
    return target


def _plan(ws: Path, scope: str = "nordwind") -> Backlog:
    return plan_backlog(build(ws), scope)


def _store(fake: FakeAdo) -> RestWorkItemStore:
    return RestWorkItemStore(ORG, PROJECT, fake.pat, transport=fake)


# --- Planung ---------------------------------------------------------------------------


def test_nordwind_backlog_snapshot(tmp_path: Path) -> None:
    text = _plan(_nordwind(tmp_path)).to_json()
    if os.environ.get("LOTSE_UPDATE_SNAPSHOTS"):
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_bytes(text.encode("utf-8"))
    assert text.encode("utf-8") == SNAPSHOT.read_bytes()


def test_nordwind_backlog_structure(tmp_path: Path) -> None:
    backlog = _plan(_nordwind(tmp_path))
    items = backlog.by_key()
    levels = [i.level for i in backlog.items]
    assert (levels.count("epic"), levels.count("feature"), levels.count("story")) == (1, 15, 2)
    epic = "product.auftragsbestand-cockpit"
    assert all(items[f"measure.{m}"].parent == epic for m in ("umsatz", "liefertreue"))
    assert items["table.fact_faktura"].parent == epic
    gap = items["finding:table_without_source:table.fact_lieferzusage"]
    assert gap.title == "Quelle für „Fakt Lieferzusage“ klären"
    assert gap.parent == "table.fact_lieferzusage"
    assert items["question.liefertermin-quelle"].parent == "measure.liefertreue"
    assert "lotse:measure.umsatz" in items["measure.umsatz"].tags("nordwind")
    # Parent steht immer vor dem Kind.
    seen: set[str] = set()
    for item in backlog.items:
        assert item.parent is None or item.parent in seen
        seen.add(item.key)


def test_cli_dry_run_is_byte_stable_and_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*_: object) -> rest.HttpResponse:
        raise AssertionError("Dry-Run darf kein Netzwerk nutzen")

    monkeypatch.setattr(rest, "urllib_transport", no_network)
    ws = _nordwind(tmp_path)
    first = runner.invoke(app, ["gen", "ado", "-w", str(ws), "--org", "x", "--project", "y"])
    assert first.exit_code == 0, first.output
    assert "Dry-Run" in first.output
    out = ws / "out" / "ado" / "backlog.json"
    content = out.read_bytes()
    assert content == SNAPSHOT.read_bytes()
    assert runner.invoke(app, ["gen", "ado", "-w", str(ws)]).exit_code == 0
    assert out.read_bytes() == content


def _mini(extra: Files) -> Files:
    files: Files = copy.deepcopy(BASE)
    files.update(extra)
    return files


def test_parent_rules_for_shared_and_orphan_measures(tmp_path: Path) -> None:
    files = _mini(
        {
            "products/a.yaml": {
                "id": "product.a",
                "name": "A",
                "owner": "stakeholder.owner",
                "serves": ["decision.d"],
                "measures": ["measure.m"],
            },
            "measures/solo.yaml": {
                "id": "measure.solo",
                "name": "Solo",
                "owner": "stakeholder.owner",
                "grain": ["dimension.k"],
                "serves": ["decision.d"],
                "from_tables": ["table.t"],
            },
            "questions/q.yaml": {
                "id": "question.q",
                "text": "Welche Hierarchie hat K?",
                "about": ["dimension.k", "measure.m"],
            },
        }
    )
    backlog = _plan(write_workspace(tmp_path / "ws", files), "mini")
    items = backlog.by_key()
    # In zwei Produkten: Parent ist das erste nach id, das zweite steht in der Beschreibung.
    assert items["measure.m"].parent == "product.a"
    assert "Auch in Datenprodukt: P" in items["measure.m"].description
    assert items["measure.solo"].parent is None
    assert items["table.t"].parent == "product.a"
    # Frage zu einer Dimension hängt unter der ersten Kennzahl mit dieser Dimension.
    assert items["question.q"].parent == "measure.m"


def test_finding_story_for_conflict(tmp_path: Path) -> None:
    files = _mini({})
    files["measures/m.yaml"]["definitions"] = [
        {"by": "stakeholder.owner", "text": "Summe X"},
        {"by": "stakeholder.owner", "text": "Summe Y"},
    ]
    items = _plan(write_workspace(tmp_path / "ws", files), "mini").by_key()
    story = items["finding:measure_definition_conflict:measure.m"]
    assert story.parent == "measure.m"
    assert story.title == "Definition von „M“ entscheiden"
    assert "Achtung: abweichende Definitionen, Entscheidung offen." in (
        items["measure.m"].description
    )


def test_plan_refuses_workspace_with_errors(tmp_path: Path) -> None:
    files = _mini({})
    files["measures/m.yaml"]["from_tables"] = ["table.gibtsnicht"]
    ws = write_workspace(tmp_path / "ws", files)
    with pytest.raises(ValueError):
        _plan(ws)
    result = runner.invoke(app, ["gen", "ado", "-w", str(ws)])
    assert result.exit_code == 1


def test_fields_escape_html_and_truncate() -> None:
    from lotse.gen.ado.plan import PlannedItem

    item = PlannedItem("measure.x", "story", "T" * 300, None, "measure.x", ("a < b",), ("c & d",))
    fields = render_fields(item)
    assert len(fields["System.Title"]) == 255
    assert fields["System.Title"] == truncate_title("T" * 300)
    assert truncate_title("a\n  b") == "a b"
    assert "a &lt; b" in fields["System.Description"]
    assert fields["Microsoft.VSTS.Common.AcceptanceCriteria"] == "<ul><li>c &amp; d</li></ul>"
    feature = render_fields(PlannedItem("m", "feature", "F", None, "m", (), ("k",)))
    assert "Microsoft.VSTS.Common.AcceptanceCriteria" not in feature
    assert "<b>Akzeptanzkriterien</b>" in feature["System.Description"]


# --- Abgleich gegen simuliertes ADO ----------------------------------------------------


def test_first_run_creates_hierarchy_second_run_no_duplicates(tmp_path: Path) -> None:
    backlog = _plan(_nordwind(tmp_path))
    fake = FakeAdo()
    target = Target("agile", area="Lotse Test\\Daten", iteration="Lotse Test\\Sprint 1")

    first = sync(backlog, _store(fake), target)
    assert len(first.created) == len(backlog.items) == len(fake.items) == 18
    by_key = {k: fake.items[i] for k, i in first.created}
    epic = by_key["product.auftragsbestand-cockpit"]
    assert epic.type == "Epic" and epic.parent is None
    assert by_key["measure.umsatz"].type == "Feature"
    assert by_key["measure.umsatz"].parent == epic.id
    story = by_key["question.liefertermin-quelle"]
    assert story.type == "User Story"
    assert story.parent == by_key["measure.liefertreue"].id
    assert "Microsoft.VSTS.Common.AcceptanceCriteria" in story.fields
    assert story.fields["System.AreaPath"] == "Lotse Test\\Daten"
    assert story.fields["System.IterationPath"] == "Lotse Test\\Sprint 1"
    assert story.tags == ["lotse", "lotse-ws:nordwind", "lotse:question.liefertermin-quelle"]

    calls_before = len(fake.writes())
    second = sync(backlog, _store(fake), target)
    assert len(fake.items) == 18
    assert second.created == [] and second.updated == [] and second.linked == []
    assert len(second.unchanged) == 18
    assert len(fake.writes()) == calls_before


def test_rerun_updates_changed_fields_and_keeps_foreign_tags(tmp_path: Path) -> None:
    ws = _nordwind(tmp_path)
    fake = FakeAdo()
    first = sync(_plan(ws), _store(fake), Target())
    umsatz = fake.items[dict(first.created)["measure.umsatz"]]
    umsatz.fields["System.Tags"] += "; Team-Tag"

    path = ws / "measures" / "umsatz.yaml"
    path.write_text(path.read_text().replace("name: Umsatz", "name: Nettoumsatz"))
    report = sync(_plan(ws), _store(fake), Target())
    assert len(fake.items) == 18
    # Der Name erscheint im Titel der Kennzahl und in den Beschreibungen von Epic und Tabelle.
    assert {k: f for k, _, f in report.updated} == {
        "measure.umsatz": ("System.Title",),
        "product.auftragsbestand-cockpit": ("System.Description",),
        "table.fact_faktura": ("System.Description",),
    }
    assert report.created == [] and report.linked == []
    assert umsatz.fields["System.Title"] == "Kennzahl: Nettoumsatz"
    assert "Team-Tag" in umsatz.tags


def test_resolved_gap_is_reported_stale_not_deleted(tmp_path: Path) -> None:
    ws = _nordwind(tmp_path)
    fake = FakeAdo()
    sync(_plan(ws), _store(fake), Target())
    path = ws / "tables" / "fact_lieferzusage.yaml"
    path.write_text(
        path.read_text().replace("kind: fact\n", "kind: fact\nfrom_sources: [source.crm]\n")
    )
    report = sync(_plan(ws), _store(fake), Target())
    assert report.created == []
    assert [k for k, _ in report.stale] == ["finding:table_without_source:table.fact_lieferzusage"]
    assert len(fake.items) == 18


def test_missing_parent_link_is_added_existing_one_not_rewired(tmp_path: Path) -> None:
    backlog = _plan(_nordwind(tmp_path))
    fake = FakeAdo()
    first = dict(sync(backlog, _store(fake), Target()).created)
    fake.items[first["measure.umsatz"]].relations.clear()
    other = fake.add("Epic", {"System.Title": "fremd"})
    fake.items[first["measure.liefertreue"]].relations[0]["url"] = (
        f"{ORG}/_apis/wit/workItems/{other.id}"
    )

    report = sync(backlog, _store(fake), Target())
    assert [k for k, _, _ in report.linked] == ["measure.umsatz"]
    assert fake.items[first["measure.umsatz"]].parent == first["product.auftragsbestand-cockpit"]
    assert fake.items[first["measure.liefertreue"]].parent == other.id
    assert any("measure.liefertreue" in w and "unverändert" in w for w in report.warnings)


def test_duplicates_and_foreign_scope(tmp_path: Path) -> None:
    backlog = _plan(_nordwind(tmp_path))
    fake = FakeAdo()
    first = dict(sync(backlog, _store(fake), Target()).created)
    tags = "lotse; lotse-ws:nordwind; lotse:measure.umsatz"
    dup = fake.add("Feature", {"System.Title": "Kopie", "System.Tags": tags})
    # Gleicher Schlüssel in anderem Workspace-Scope wird ignoriert.
    fake.add("Feature", {"System.Tags": "lotse; lotse-ws:anders; lotse:measure.umsatz"})
    # Präfix eines Schlüssels darf nicht treffen.
    fake.add("Feature", {"System.Tags": "lotse-ws:nordwind; lotse:measure.umsatz-alt"})

    report = sync(backlog, _store(fake), Target())
    assert report.created == []
    assert any(f"#{dup.id}" in w for w in report.warnings)
    assert dict(report.unchanged)["measure.umsatz"] == first["measure.umsatz"]
    assert [k for k, _ in report.stale] == ["measure.umsatz-alt"]


def test_scrum_process_and_type_preflight(tmp_path: Path) -> None:
    backlog = _plan(_nordwind(tmp_path))
    scrum = FakeAdo(types=SCRUM)
    with pytest.raises(AdoError, match="--process scrum"):
        sync(backlog, _store(scrum), Target("agile"))
    assert scrum.writes() == []
    report = sync(backlog, _store(scrum), Target("scrum"))
    story = scrum.items[dict(report.created)["question.liefertermin-quelle"]]
    assert story.type == "Product Backlog Item"


def test_auth_error_does_not_leak_pat(tmp_path: Path) -> None:
    fake = FakeAdo(pat="richtig")
    store = RestWorkItemStore(ORG, PROJECT, "falsch-geheim", transport=fake)
    with pytest.raises(AdoError) as exc:
        sync(_plan(_nordwind(tmp_path)), store, Target())
    assert "401" in str(exc.value)
    assert "falsch-geheim" not in str(exc.value)


def test_org_url_and_type_encoding() -> None:
    fake = FakeAdo()
    store = RestWorkItemStore("testorg", PROJECT, fake.pat, transport=fake)
    assert store.project_url == f"{ORG}/Lotse%20Test"
    store.create("User Story", {"System.Title": "x"}, None)
    assert fake.calls[-1][1].startswith(f"{ORG}/Lotse%20Test/_apis/wit/workitems/$User%20Story?")


# --- CLI -------------------------------------------------------------------------------


def test_cli_apply_requires_org_project_and_pat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("AZURE_DEVOPS_EXT_PAT", "LOTSE_ADO_PAT"):
        monkeypatch.delenv(name, raising=False)
    ws = _nordwind(tmp_path)
    result = runner.invoke(app, ["gen", "ado", "-w", str(ws), "--apply"])
    assert result.exit_code == 2
    assert "--org" in result.output and "--project" in result.output
    assert "LOTSE_ADO_PAT" in result.output
    assert not (ws / "out").exists()


def test_cli_apply_against_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeAdo(pat="cli-pat")
    monkeypatch.setattr(rest, "urllib_transport", fake)
    monkeypatch.delenv("AZURE_DEVOPS_EXT_PAT", raising=False)
    monkeypatch.setenv("LOTSE_ADO_PAT", "cli-pat")
    ws = _nordwind(tmp_path)
    args = ["gen", "ado", "-w", str(ws), "--apply", "--org", "testorg", "--project", PROJECT]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert "18 angelegt" in first.output
    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert "0 angelegt, 0 geändert, 0 verknüpft, 18 unverändert" in second.output
    assert len(fake.items) == 18
    assert "cli-pat" not in first.output + second.output
