"""Abfragen auf dem gebauten Index: nächste Frage und Fortschritt je Stufe."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb

QUESTION_TEMPLATES: dict[str, str] = {
    "schema": "Die Datei ist ungültig. Bitte korrigieren: {message}",
    "dangling_reference": "„{name}“ verweist auf etwas, das es nicht gibt. Fehlt die Entität, "
    "oder ist der Verweis falsch? ({message})",
    "measure_definition_conflict": "Für „{name}“ gibt es abweichende Definitionen. Welche gilt, "
    "und wer entscheidet?",
    "missing_owner": "Wer verantwortet „{name}“ fachlich?",
    "missing_grain": "Auf welcher Ebene wird „{name}“ betrachtet (z. B. je Kunde, Produkt, Monat)?",
    "measure_without_table": "Aus welchen Daten wird „{name}“ berechnet?",
    "table_without_source": "Aus welchem Quellsystem kommen die Daten für „{name}“?",
    "measure_without_decision": "Welche Entscheidung stützt „{name}“? Wenn keine: Brauchen wir "
    "die Kennzahl?",
    "dimension_unused": "Welche Kennzahl wird nach „{name}“ ausgewertet? Wenn keine: Brauchen "
    "wir die Dimension?",
}

_NEXT_SQL = """
SELECT f.rule, f.severity, f.node_id, f.message,
       n.type, n.name, n.stage, n.file, st.ord, st.label,
       (SELECT min(e.dst) FROM edge e WHERE e.src = f.node_id AND e.kind = 'owner') AS owner
FROM finding f
JOIN severity s ON s.name = f.severity
LEFT JOIN node n ON n.id = f.node_id
LEFT JOIN stage st ON st.name = n.stage
ORDER BY (f.severity = 'error') DESC, coalesce(st.ord, 0), s.rank,
         f.node_id NULLS FIRST, f.rule, f.message
"""


@dataclass(frozen=True)
class NextQuestion:
    rule: str
    severity: str
    node_id: str | None
    node_type: str | None
    node_name: str | None
    stage: str | None
    stage_label: str | None
    file: str | None
    owner: str | None
    message: str
    question: str
    related: list[dict[str, str]]
    open_findings: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StageStatus:
    stage: str
    label: str
    state: str | None
    nodes: int
    clean: int
    findings: dict[str, int]

    @property
    def progress(self) -> float:
        return self.clean / self.nodes if self.nodes else 0.0


def _connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path), read_only=True)


def next_question(db_path: Path) -> NextQuestion | None:
    con = _connect(db_path)
    try:
        rows = con.execute(_NEXT_SQL).fetchall()
        if not rows:
            return None
        rule, severity, node_id, message, ntype, name, stage, file, _, label, owner = rows[0]
        related: list[dict[str, str]] = []
        if node_id:
            related = [
                {"kind": k, "id": i, "direction": d}
                for k, i, d in con.execute(
                    """
                    SELECT kind, dst, 'out' FROM edge WHERE src = ?
                    UNION ALL
                    SELECT kind, src, 'in' FROM edge WHERE dst = ?
                    ORDER BY 3 DESC, 1, 2
                    """,
                    [node_id, node_id],
                ).fetchall()
            ]
    finally:
        con.close()
    template = QUESTION_TEMPLATES.get(rule, "{message}")
    question = template.format(name=name or node_id or "", message=message)
    return NextQuestion(
        rule=rule,
        severity=severity,
        node_id=node_id,
        node_type=ntype,
        node_name=name,
        stage=stage,
        stage_label=label,
        file=file,
        owner=owner,
        message=message,
        question=question,
        related=related,
        open_findings=len(rows),
    )


def stage_status(db_path: Path) -> list[StageStatus]:
    con = _connect(db_path)
    try:
        stages = con.execute(
            """
            SELECT st.name, st.label, w.value,
                   count(n.id) AS nodes,
                   count(n.id) FILTER (
                       WHERE NOT EXISTS (SELECT 1 FROM finding f WHERE f.node_id = n.id)
                   ) AS clean
            FROM stage st
            LEFT JOIN node n ON n.stage = st.name
            LEFT JOIN workspace w ON w.key = 'stage.' || st.name
            GROUP BY st.name, st.label, st.ord, w.value
            ORDER BY st.ord
            """
        ).fetchall()
        counts = con.execute(
            """
            SELECT n.stage, f.severity, count(*)
            FROM finding f JOIN node n ON n.id = f.node_id
            WHERE n.stage IS NOT NULL
            GROUP BY 1, 2
            """
        ).fetchall()
    finally:
        con.close()
    by_stage: dict[str, dict[str, int]] = {}
    for stage, severity, count in counts:
        by_stage.setdefault(stage, {})[severity] = count
    return [
        StageStatus(name, label, state, nodes, clean, by_stage.get(name, {}))
        for name, label, state, nodes, clean in stages
    ]
