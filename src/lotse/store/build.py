"""Baut den DuckDB-Index vollständig aus den YAML-Dateien und führt die Regeln aus."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import duckdb

from lotse.model.finding import Finding
from lotse.model.registry import SEVERITIES, STAGES
from lotse.store.graph import Graph, build_graph
from lotse.store.loader import LoadResult, load_workspace
from lotse.store.workspace import index_path

DDL = """
CREATE TABLE node (
    id VARCHAR PRIMARY KEY, type VARCHAR NOT NULL, name VARCHAR NOT NULL,
    status VARCHAR, stage VARCHAR, file VARCHAR NOT NULL
);
CREATE TABLE edge (src VARCHAR NOT NULL, dst VARCHAR NOT NULL, kind VARCHAR NOT NULL);
CREATE TABLE attr (id VARCHAR NOT NULL, key VARCHAR NOT NULL, value VARCHAR NOT NULL);
CREATE TABLE definition (
    measure_id VARCHAR NOT NULL, stakeholder_id VARCHAR NOT NULL,
    text VARCHAR NOT NULL, statement_id VARCHAR
);
CREATE TABLE finding (
    rule VARCHAR NOT NULL, severity VARCHAR NOT NULL, node_id VARCHAR, message VARCHAR NOT NULL
);
CREATE TABLE stage (name VARCHAR PRIMARY KEY, ord INTEGER NOT NULL, label VARCHAR NOT NULL);
CREATE TABLE severity (name VARCHAR PRIMARY KEY, rank INTEGER NOT NULL);
CREATE TABLE workspace (key VARCHAR PRIMARY KEY, value VARCHAR);
"""

FINDING_ORDER = """
SELECT f.rule, f.severity, f.node_id, f.message
FROM finding f
JOIN severity s ON s.name = f.severity
LEFT JOIN node n ON n.id = f.node_id
LEFT JOIN stage st ON st.name = n.stage
ORDER BY s.rank, coalesce(st.ord, 99), f.node_id NULLS FIRST, f.rule, f.message
"""


class RuleError(Exception):
    pass


@dataclass(frozen=True)
class Rule:
    name: str
    sql: str


@dataclass
class BuildResult:
    workspace: Path
    db_path: Path
    loaded: LoadResult
    graph: Graph
    findings: list[Finding]

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    @property
    def has_errors(self) -> bool:
        return self.count("error") > 0


def load_rules() -> list[Rule]:
    """Alle ``*.sql`` aus ``lotse.rules``, sortiert nach Dateiname."""
    root = resources.files("lotse.rules")
    rules = [
        Rule(entry.name.removesuffix(".sql"), entry.read_text(encoding="utf-8"))
        for entry in root.iterdir()
        if entry.name.endswith(".sql")
    ]
    return sorted(rules, key=lambda r: r.name)


def run_rules(con: duckdb.DuckDBPyConnection, rules: list[Rule]) -> list[Finding]:
    findings: list[Finding] = []
    for rule in rules:
        rows = con.execute(rule.sql).fetchall()
        for row in rows:
            if len(row) != 4:
                raise RuleError(f"Regel {rule.name}: erwartet 4 Spalten, erhalten {len(row)}")
            name, severity, node_id, message = row
            if name != rule.name:
                raise RuleError(f"Regel {rule.name}: Spalte rule ist {name!r}")
            if severity not in SEVERITIES:
                raise RuleError(f"Regel {rule.name}: unbekannte Severity {severity!r}")
            findings.append(Finding(name, severity, node_id, message))
    return findings


def write_index(con: duckdb.DuckDBPyConnection, loaded: LoadResult, graph: Graph) -> None:
    con.execute(DDL)
    if graph.nodes:
        con.executemany("INSERT INTO node VALUES (?, ?, ?, ?, ?, ?)", graph.nodes)
    if graph.edges:
        con.executemany("INSERT INTO edge VALUES (?, ?, ?)", graph.edges)
    if graph.attrs:
        con.executemany("INSERT INTO attr VALUES (?, ?, ?)", graph.attrs)
    if graph.definitions:
        con.executemany("INSERT INTO definition VALUES (?, ?, ?, ?)", graph.definitions)
    con.executemany(
        "INSERT INTO stage VALUES (?, ?, ?)", [(t.name, t.stage, t.label) for t in STAGES]
    )
    con.executemany(
        "INSERT INTO severity VALUES (?, ?)", [(s, i) for i, s in enumerate(SEVERITIES)]
    )
    cfg = loaded.config
    meta = [("name", cfg.name if cfg else None), ("platform", cfg.platform if cfg else None)]
    if cfg:
        meta += [(f"stage.{k}", v) for k, v in sorted(cfg.stages.items())]
    con.executemany("INSERT INTO workspace VALUES (?, ?)", meta)


def build(workspace: Path, db_path: Path | None = None) -> BuildResult:
    """Vollständiger Neubau. Die DuckDB-Datei wird vorher gelöscht."""
    loaded = load_workspace(workspace)
    graph = build_graph(loaded)
    target = db_path or index_path(loaded.workspace)
    target.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", ".wal"):
        Path(f"{target}{suffix}").unlink(missing_ok=True)

    con = duckdb.connect(str(target))
    try:
        write_index(con, loaded, graph)
        findings = list(loaded.problems) + run_rules(con, load_rules())
        rows = [(f.rule, f.severity, f.node_id, f.message) for f in findings]
        if rows:
            con.executemany("INSERT INTO finding VALUES (?, ?, ?, ?)", rows)
        ordered = [Finding(*r) for r in con.execute(FINDING_ORDER).fetchall()]
    finally:
        con.close()
    return BuildResult(loaded.workspace, target, loaded, graph, ordered)
