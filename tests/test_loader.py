from __future__ import annotations

from collections.abc import Callable

from conftest import Files

from lotse.model.finding import Finding

Run = Callable[[Files], list[Finding]]


def schema_errors(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.rule == "schema"]


def test_wrong_reference_type_is_schema_error(run: Run, base: Files) -> None:
    base["measures/m.yaml"]["serves"] = ["table.t"]
    errors = schema_errors(run(base))
    assert len(errors) == 1
    assert errors[0].severity == "error"
    assert errors[0].node_id == "measure.m"
    assert "measures/m.yaml" in errors[0].message


def test_unknown_field_is_rejected(run: Run, base: Files) -> None:
    base["tables/t.yaml"]["farbe"] = "blau"
    assert "farbe" in schema_errors(run(base))[0].message


def test_id_must_match_filename(run: Run, base: Files) -> None:
    base["sources/anders.yaml"] = {"id": "source.s2", "name": "S2", "system": "X"}
    errors = schema_errors(run(base))
    assert len(errors) == 1
    assert "source.anders" in errors[0].message


def test_id_prefix_must_match_folder(run: Run, base: Files) -> None:
    base["sources/x.yaml"] = {"id": "table.x", "name": "X", "system": "X"}
    assert len(schema_errors(run(base))) == 1


def test_invalid_yaml_and_empty_file(run: Run, base: Files) -> None:
    base["sources/kaputt.yaml"] = "id: [unterminated"
    base["sources/leer.yaml"] = ""
    messages = sorted(f.message for f in schema_errors(run(base)))
    assert len(messages) == 2
    assert "keine Daten" in messages[1] or "keine Daten" in messages[0]


def test_invalid_entity_is_not_indexed_but_others_are(run: Run, base: Files) -> None:
    # Ungültige Tabelle fehlt im Index, Verweise darauf werden dangling.
    base["tables/t.yaml"]["kind"] = "unbekannt"
    rules = {f.rule for f in run(base)}
    assert rules == {"schema", "dangling_reference"}


def test_invalid_workspace_config(run: Run, base: Files) -> None:
    base["lotse.yaml"] = {"name": "X", "platform": "snowflake"}
    errors = schema_errors(run(base))
    assert len(errors) == 1
    assert "lotse.yaml" in errors[0].message
