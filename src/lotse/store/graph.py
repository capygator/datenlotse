"""Zerlegt geladene Entitäten in Knoten, Kanten, Attribute und Definitionen."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from lotse.model.entities import Measure, Table
from lotse.store.loader import LoadedEntity, LoadResult

REF_FIELDS = frozenset(
    {
        "about",
        "answer",
        "by",
        "from_sources",
        "from_tables",
        "grain",
        "measures",
        "owner",
        "serves",
        "statement",
    }
)
"""Felder, deren Werte IDs sind und Kanten ergeben (Kantenart = Feldname)."""

_NODE_FIELDS = frozenset({"id", "name", "status"})
_STRUCTURED = frozenset({"definitions", "columns", "quality"})


@dataclass
class Graph:
    nodes: list[tuple[str, str, str, str | None, str | None, str]] = field(default_factory=list)
    edges: list[tuple[str, str, str]] = field(default_factory=list)
    attrs: list[tuple[str, str, str]] = field(default_factory=list)
    definitions: list[tuple[str, str, str, str | None]] = field(default_factory=list)


def _scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _node(entity: LoadedEntity) -> tuple[str, str, str, str | None, str | None, str]:
    data = entity.model.model_dump()
    name = data.get("name") or data.get("text") or entity.id
    status = data.get("status")
    stage = entity.type.name if entity.type.stage is not None else None
    return (entity.id, entity.type.name, str(name), status, stage, entity.file)


def build_graph(loaded: LoadResult) -> Graph:
    graph = Graph()
    edges: set[tuple[str, str, str]] = set()
    attrs: list[tuple[str, str, str]] = []
    for entity in loaded.entities:
        src = entity.id
        graph.nodes.append(_node(entity))
        data = entity.model.model_dump(exclude_none=True)
        for key, value in data.items():
            if key in _NODE_FIELDS or key in _STRUCTURED:
                continue
            if key in REF_FIELDS:
                for dst in value if isinstance(value, list) else [value]:
                    edges.add((src, dst, key))
            elif isinstance(value, list):
                attrs.extend((src, key, _scalar(v)) for v in value)
            elif isinstance(value, dict):
                attrs.extend((src, f"{key}.{k}", _scalar(v)) for k, v in sorted(value.items()))
            else:
                attrs.append((src, key, _scalar(value)))

        model = entity.model
        if isinstance(model, Measure):
            for d in model.definitions:
                graph.definitions.append((src, d.by, d.text, d.statement))
                edges.add((src, d.by, "definition_by"))
                if d.statement:
                    edges.add((src, d.statement, "definition_statement"))
            attrs.extend((src, "quality", q.rule) for q in model.quality)
        if isinstance(model, Table):
            for pos, col in enumerate(model.columns):
                # pos erhält die YAML-Reihenfolge, obwohl attr sortiert gespeichert wird.
                payload = {"pos": pos, **col.model_dump(exclude_none=True)}
                attrs.append((src, "column", json.dumps(payload, sort_keys=True)))
                if col.references:
                    edges.add((src, col.references, "column_references"))

    graph.nodes.sort()
    graph.edges = sorted(edges)
    graph.attrs = sorted(attrs)
    graph.definitions.sort(key=lambda r: (r[0], r[1], r[2], r[3] or ""))
    return graph
