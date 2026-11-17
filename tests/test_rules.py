"""Je Regel ein positives und ein negatives Fixture."""

from __future__ import annotations

from collections.abc import Callable

from conftest import Files

from lotse.model.finding import Finding
from lotse.store.build import load_rules

Run = Callable[[Files], list[Finding]]


def fired(findings: list[Finding], rule: str) -> list[str | None]:
    return [f.node_id for f in findings if f.rule == rule]


def test_all_eight_rules_ship() -> None:
    assert [r.name for r in load_rules()] == [
        "dangling_reference",
        "dimension_unused",
        "measure_definition_conflict",
        "measure_without_decision",
        "measure_without_table",
        "missing_grain",
        "missing_owner",
        "table_without_source",
    ]


def test_base_workspace_is_clean(run: Run, base: Files) -> None:
    assert run(base) == []


# measure_without_decision
def test_measure_without_decision_positive(run: Run, base: Files) -> None:
    del base["measures/m.yaml"]["serves"]
    findings = run(base)
    assert fired(findings, "measure_without_decision") == ["measure.m"]
    assert findings[0].severity == "warn"


def test_measure_without_decision_negative(run: Run, base: Files) -> None:
    # Produkt dient der Entscheidung, Kennzahl selbst auch: kein Befund.
    assert fired(run(base), "measure_without_decision") == []


# measure_without_table
def test_measure_without_table_positive(run: Run, base: Files) -> None:
    del base["measures/m.yaml"]["from_tables"]
    assert fired(run(base), "measure_without_table") == ["measure.m"]


def test_measure_without_table_negative(run: Run, base: Files) -> None:
    # Dimension ohne Tabelle betrifft diese Regel nicht.
    del base["dimensions/k.yaml"]["from_tables"]
    assert fired(run(base), "measure_without_table") == []


# table_without_source
def test_table_without_source_positive(run: Run, base: Files) -> None:
    del base["tables/t.yaml"]["from_sources"]
    findings = run(base)
    assert fired(findings, "table_without_source") == ["table.t"]
    assert findings[0].severity == "gap"


def test_table_without_source_negative(run: Run, base: Files) -> None:
    base["tables/u.yaml"] = {
        "id": "table.u",
        "name": "U",
        "kind": "dimension",
        "from_sources": ["source.s"],
    }
    assert fired(run(base), "table_without_source") == []


# measure_definition_conflict
def test_measure_definition_conflict_positive(run: Run, base: Files) -> None:
    base["stakeholders/zwei.yaml"] = {"id": "stakeholder.zwei", "name": "Zwei"}
    base["measures/m.yaml"]["definitions"].append({"by": "stakeholder.zwei", "text": "Summe Y"})
    findings = run(base)
    assert fired(findings, "measure_definition_conflict") == ["measure.m"]
    assert findings[0].severity == "conflict"
    assert "stakeholder.owner, stakeholder.zwei" in findings[0].message


def test_measure_definition_conflict_negative(run: Run, base: Files) -> None:
    # Gleicher Text mit anderem Leerraum ist kein Konflikt.
    base["stakeholders/zwei.yaml"] = {"id": "stakeholder.zwei", "name": "Zwei"}
    base["measures/m.yaml"]["definitions"].append({"by": "stakeholder.zwei", "text": " Summe   X "})
    assert fired(run(base), "measure_definition_conflict") == []


# missing_owner
def test_missing_owner_positive(run: Run, base: Files) -> None:
    del base["measures/m.yaml"]["owner"]
    del base["products/p.yaml"]["owner"]
    assert fired(run(base), "missing_owner") == ["product.p", "measure.m"]


def test_missing_owner_negative(run: Run, base: Files) -> None:
    # Tabellen und Dimensionen brauchen keinen Owner.
    assert "owner" not in base["tables/t.yaml"]
    assert fired(run(base), "missing_owner") == []


# missing_grain
def test_missing_grain_positive(run: Run, base: Files) -> None:
    base["measures/m.yaml"]["grain"] = []
    assert fired(run(base), "missing_grain") == ["measure.m"]


def test_missing_grain_negative(run: Run, base: Files) -> None:
    assert fired(run(base), "missing_grain") == []


# dimension_unused
def test_dimension_unused_positive(run: Run, base: Files) -> None:
    base["dimensions/frei.yaml"] = {"id": "dimension.frei", "name": "Frei"}
    findings = run(base)
    assert fired(findings, "dimension_unused") == ["dimension.frei"]
    assert findings[0].severity == "info"


def test_dimension_unused_negative(run: Run, base: Files) -> None:
    assert fired(run(base), "dimension_unused") == []


# dangling_reference
def test_dangling_reference_positive(run: Run, base: Files) -> None:
    base["measures/m.yaml"]["serves"] = ["decision.gibtsnicht"]
    base["measures/m.yaml"]["definitions"][0]["by"] = "stakeholder.niemand"
    findings = run(base)
    assert fired(findings, "dangling_reference") == ["measure.m", "measure.m"]
    messages = " ".join(f.message for f in findings if f.rule == "dangling_reference")
    assert "decision.gibtsnicht" in messages
    assert "stakeholder.niemand" in messages
    assert all(f.severity == "error" for f in findings if f.rule == "dangling_reference")


def test_dangling_reference_negative(run: Run, base: Files) -> None:
    assert fired(run(base), "dangling_reference") == []
