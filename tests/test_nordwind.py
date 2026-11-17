"""Abnahme M1: Der Nordwind-Endzustand baut fehlerfrei und deterministisch."""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
from conftest import NORDWIND

from lotse.model.finding import Finding
from lotse.store.build import build

EXPECTED = [
    Finding(
        "table_without_source",
        "gap",
        "table.fact_lieferzusage",
        "Tabelle „Fakt Lieferzusage“ hat keine Quelle (from_sources fehlt)",
    )
]


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "nordwind"
    shutil.copytree(NORDWIND, target, ignore=shutil.ignore_patterns(".lotse"))
    return target


def test_nordwind_builds_without_errors(tmp_path: Path) -> None:
    result = build(_copy(tmp_path))
    assert not result.has_errors
    assert result.findings == EXPECTED


def test_nordwind_scenario_size(tmp_path: Path) -> None:
    result = build(_copy(tmp_path))
    types = [n[1] for n in result.graph.nodes]
    assert types.count("stakeholder") == 4
    assert types.count("measure") == 6
    assert types.count("dimension") == 5
    assert types.count("source") == 3
    assert types.count("decision") == 1
    assert types.count("product") == 1


def _dump(db: Path) -> dict[str, list[tuple[object, ...]]]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        tables = ["node", "edge", "attr", "definition", "finding", "stage", "severity", "workspace"]
        return {t: con.execute(f"SELECT * FROM {t} ORDER BY ALL").fetchall() for t in tables}
    finally:
        con.close()


def test_rebuild_is_deterministic(tmp_path: Path) -> None:
    ws = _copy(tmp_path)
    first = build(ws)
    snapshot = _dump(first.db_path)
    shutil.rmtree(ws / ".lotse")
    second = build(ws)
    assert second.findings == first.findings
    assert _dump(second.db_path) == snapshot
