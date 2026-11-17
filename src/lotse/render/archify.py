"""Archify-Renderer (JSON-IR für Archify ab 3.2).

Format nach den Schemas aus https://github.com/tt-a1i/archify (``archify/schemas/``, Version
3.2.0, Commit 4478129), vendored unter ``lotse/render/schemas/archify/``:

- Sichten der Art ``flow`` → ``diagram_type: dataflow`` (Stufen = Spalten der Sicht, höchstens 5)
- Sichten der Art ``erd`` → ``diagram_type: erd`` (Tabellen, Spalten, Fremdschlüssel)

Archify kennt keinen Knotenstatus; Status und Befund stehen deshalb als Text im ``tag``.
Jede Ausgabe wird vor dem Schreiben gegen das Schema validiert.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from lotse.render import RenderError, marker, safe_id
from lotse.views import ViewNode, ViewResult

SCHEMA_PACKAGE = "lotse.render.schemas.archify"
SCHEMA_BASE = "https://github.com/tt-a1i/archify/schemas/"
MAX_STAGES = 5
MAX_GRID = 12

NODE_TYPE = {
    "source": "external",
    "table": "database",
    "measure": "backend",
    "block": "backend",
    "product": "frontend",
    "decision": "external",
}
NODE_ICON = {"decision": "flag"}
CARD_ORDER = ("error", "conflict", "gap", "warn", "info")


@cache
def _validators() -> dict[str, Draft202012Validator]:
    root = resources.files(SCHEMA_PACKAGE)
    schemas = {
        name: json.loads((root / f"{name}.schema.json").read_text(encoding="utf-8"))
        for name in ("common", "dataflow", "erd")
    }
    registry: Registry[Any] = Registry().with_resources(
        (f"{SCHEMA_BASE}{name}.schema.json", Resource.from_contents(schema))
        for name, schema in schemas.items()
    )
    return {
        name: Draft202012Validator(schemas[name], registry=registry) for name in ("dataflow", "erd")
    }


def validate(document: dict[str, Any]) -> list[str]:
    """Schemafehler als Texte (leer = gültig)."""
    validator = _validators()[document["diagram_type"]]
    return sorted(
        f"{'/'.join(str(p) for p in err.absolute_path) or '(root)'}: {err.message}"
        for err in validator.iter_errors(document)
    )


def _type(node: ViewNode) -> str:
    return node.id.split(".", 1)[0]


def _meta(view: ViewResult, **extra: Any) -> dict[str, Any]:
    title = f"{view.workspace_name}: {view.view.title}" if view.workspace_name else view.view.title
    meta: dict[str, Any] = {"title": title, "locale": "de"}
    if view.view.description:
        meta["subtitle"] = view.view.description
    meta["output"] = f"{view.view.name}.html"
    meta.update(extra)
    return meta


def _finding_card(view: ViewResult) -> list[dict[str, Any]]:
    items = [
        f"{n.label}: {marker(None, n.finding)}"
        for sev in CARD_ORDER
        for n in view.nodes
        if n.finding == sev
    ]
    if not items:
        return []
    return [{"dot": "amber", "title": "Offene Befunde", "items": items}]


class ArchifyRenderer:
    name = "archify"
    extension = "json"

    def render(self, view: ViewResult) -> str:
        doc = self.document(view)
        errors = validate(doc)
        if errors:
            raise RenderError("Archify-Schema verletzt:\n" + "\n".join(errors))
        return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"

    def document(self, view: ViewResult) -> dict[str, Any]:
        return self._erd(view) if view.view.kind == "erd" else self._dataflow(view)

    def _dataflow(self, view: ViewResult) -> dict[str, Any]:
        lanes = view.lanes()
        if not 2 <= len(lanes) <= MAX_STAGES:
            raise RenderError(
                f"Archify Data Flow braucht 2 bis {MAX_STAGES} Stufen, Sicht "
                f"{view.view.name} hat {len(lanes)}"
            )
        stage_of = {lane: i for i, (lane, _) in enumerate(lanes)}
        status = {n.id: n.status for n in view.nodes}
        nodes = []
        for lane, _ in lanes:
            for row, n in enumerate(x for x in view.nodes if x.lane == lane):
                node: dict[str, Any] = {
                    "id": safe_id(n.id),
                    "type": NODE_TYPE.get(_type(n), "backend"),
                    "label": n.label,
                }
                if n.sublabel:
                    node["sublabel"] = n.sublabel
                mark = marker(n.status, n.finding)
                if mark:
                    node["tag"] = mark
                if _type(n) in NODE_ICON:
                    node["icon"] = NODE_ICON[_type(n)]
                node["stage"] = stage_of[lane]
                node["row"] = row
                nodes.append(node)
        flows = []
        for e in view.edges:
            flow: dict[str, Any] = {"from": safe_id(e.src), "to": safe_id(e.dst), "label": e.label}
            if status.get(e.src) != "agreed" or status.get(e.dst) != "agreed":
                flow["variant"] = "dashed"
            flows.append(flow)
        doc: dict[str, Any] = {
            "schema_version": 1,
            "diagram_type": "dataflow",
            "meta": _meta(view),
            "stages": [{"label": label} for _, label in lanes],
            "nodes": nodes,
            "flows": flows,
        }
        cards = _finding_card(view)
        if cards:
            doc["cards"] = cards
        return doc

    def _erd(self, view: ViewResult) -> dict[str, Any]:
        slug = {n.id: n.id.split(".", 1)[-1] for n in view.nodes}
        ent_id = {n.id: safe_id(slug[n.id]) for n in view.nodes}
        # Fremdschlüssel → "tabelle.spalte" der Zieltabelle, falls die Zielspalte bekannt ist.
        fk_target: dict[tuple[str, str], str] = {}
        for e in view.edges:
            detail = e.detail or {}
            if detail.get("to_column"):
                fk_target[(e.src, detail["from_column"])] = f"{ent_id[e.dst]}.{detail['to_column']}"

        entities = []
        row = 0
        for lane, _ in view.lanes():
            members = [n for n in view.nodes if n.lane == lane]
            for i, n in enumerate(members):
                entity: dict[str, Any] = {"id": ent_id[n.id], "label": n.label}
                mark = marker(n.status, n.finding)
                if mark:
                    entity["sublabel"] = mark
                entity["row"] = row + i // (MAX_GRID + 1)
                entity["col"] = i % (MAX_GRID + 1)
                attributes = []
                for col in n.detail or []:
                    attr: dict[str, Any] = {"name": col["name"], "type": col.get("type", "string")}
                    keys = []
                    if col.get("key"):
                        keys.append("pk")
                    target = fk_target.get((n.id, col["name"]))
                    if target:
                        keys.append("fk")
                    if keys:
                        attr["key"] = keys[0] if len(keys) == 1 else keys
                    if target:
                        attr["references"] = target
                    attributes.append(attr)
                entity["attributes"] = attributes
                entities.append(entity)
            row += (len(members) + MAX_GRID) // (MAX_GRID + 1)
            if row > MAX_GRID:
                raise RenderError("Archify ERD: Raster mit mehr als 13 Zeilen")
        relationships = []
        for e in view.edges:
            rel: dict[str, Any] = {
                "from": ent_id[e.src],
                "to": ent_id[e.dst],
                "label": e.label,
                "fromCardinality": "many",
                "toCardinality": "one",
            }
            relationships.append(rel)
        doc: dict[str, Any] = {
            "schema_version": 1,
            "diagram_type": "erd",
            "meta": _meta(view, quality_profile="standard"),
            "layout": {"mode": "grid"},
            "entities": entities,
            "relationships": relationships,
        }
        cards = _finding_card(view)
        if cards:
            doc["cards"] = cards
        return doc
