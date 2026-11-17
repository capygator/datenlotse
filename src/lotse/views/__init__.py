"""Benannte Sichten auf den DuckDB-Index.

Jede Sicht ist eine Datei ``<name>.sql`` mit Kopfzeilen ``-- title:``, ``-- kind:`` (``flow``
oder ``erd``) und ``-- description:``. Die Abfrage liefert genau diese Spalten::

    element  'node' | 'edge'
    id       Knoten-ID (nur node)
    label    Knotenname bzw. Kantenbeschriftung
    sublabel optionale zweite Zeile (nur node)
    lane     Spalte/Stufe als Ganzzahl ab 0 (nur node)
    lane_label
    status   draft | agreed | conflict (nur node)
    finding  schwerste Severity eines offenen Befunds oder NULL (nur node)
    src, dst Kantenenden (nur edge)
    detail   JSON oder NULL (sichtabhängig, z. B. Spalten einer Tabelle)

Renderer bekommen ein :class:`ViewResult` und kennen die SQL-Dateien nicht.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import duckdb

ViewKind = Literal["flow", "erd"]
COLUMNS = (
    "element",
    "id",
    "label",
    "sublabel",
    "lane",
    "lane_label",
    "status",
    "finding",
    "src",
    "dst",
    "detail",
)


class ViewError(Exception):
    pass


@dataclass(frozen=True)
class View:
    name: str
    title: str
    kind: ViewKind
    description: str
    sql: str


@dataclass(frozen=True)
class ViewNode:
    id: str
    label: str
    lane: int
    lane_label: str
    sublabel: str | None = None
    status: str | None = None
    finding: str | None = None
    detail: Any = None


@dataclass(frozen=True)
class ViewEdge:
    src: str
    dst: str
    label: str
    detail: Any = None


@dataclass
class ViewResult:
    view: View
    workspace_name: str
    nodes: list[ViewNode] = field(default_factory=list)
    edges: list[ViewEdge] = field(default_factory=list)

    def lanes(self) -> list[tuple[int, str]]:
        """Belegte Spalten, sortiert."""
        return sorted({(n.lane, n.lane_label) for n in self.nodes})


def _header(sql: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in sql.splitlines():
        if not line.startswith("--"):
            break
        key, sep, value = line[2:].strip().partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta


def _parse(name: str, sql: str) -> View:
    meta = _header(sql)
    kind: ViewKind
    if meta.get("kind") == "flow":
        kind = "flow"
    elif meta.get("kind") == "erd":
        kind = "erd"
    else:
        raise ViewError(f"Sicht {name}: Kopfzeile '-- kind: flow|erd' fehlt")
    return View(name, meta.get("title", name), kind, meta.get("description", ""), sql)


def list_views() -> list[View]:
    root = resources.files("lotse.views")
    views = [
        _parse(entry.name.removesuffix(".sql"), entry.read_text(encoding="utf-8"))
        for entry in root.iterdir()
        if entry.name.endswith(".sql")
    ]
    return sorted(views, key=lambda v: v.name)


def get_view(name: str) -> View:
    for view in list_views():
        if view.name == name:
            return view
    known = ", ".join(v.name for v in list_views())
    raise ViewError(f"Unbekannte Sicht {name!r}. Verfügbar: {known}")


def _json(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def run_view(db_path: Path, view: View) -> ViewResult:
    """Führt die Sicht gegen den Index aus; Ergebnis ist deterministisch sortiert."""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        cur = con.execute(view.sql)
        names = tuple(d[0] for d in cur.description or ())
        if names != COLUMNS:
            raise ViewError(f"Sicht {view.name}: Spalten {names}, erwartet {COLUMNS}")
        rows = cur.fetchall()
        ws = con.execute("SELECT value FROM workspace WHERE key = 'name'").fetchone()
    finally:
        con.close()

    result = ViewResult(view, str(ws[0]) if ws and ws[0] else "")
    for element, nid, label, sublabel, lane, lane_label, status, finding, src, dst, detail in rows:
        if element == "node":
            result.nodes.append(
                ViewNode(
                    nid, label, int(lane), lane_label, sublabel, status, finding, _json(detail)
                )
            )
        elif element == "edge":
            result.edges.append(ViewEdge(src, dst, label, _json(detail)))
        else:
            raise ViewError(f"Sicht {view.name}: unbekanntes element {element!r}")
    result.nodes.sort(key=lambda n: (n.lane, n.label, n.id))
    result.edges.sort(key=lambda e: (e.src, e.dst, e.label))
    ids = {n.id for n in result.nodes}
    for e in result.edges:
        if e.src not in ids or e.dst not in ids:
            raise ViewError(f"Sicht {view.name}: Kante {e.src} → {e.dst} ohne Knoten")
    return result
