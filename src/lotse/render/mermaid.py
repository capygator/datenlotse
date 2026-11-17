"""Mermaid-Renderer: ``flow`` → ``flowchart LR``, ``erd`` → ``erDiagram``."""

from __future__ import annotations

import re

from lotse.render import marker, safe_id
from lotse.views import ViewNode, ViewResult

CLASS_DEFS = (
    "    classDef agreed fill:#e8f5e9,stroke:#2e7d32,color:#1b1b1b",
    "    classDef draft fill:#fff8e1,stroke:#f9a825,color:#1b1b1b",
    "    classDef conflict fill:#ffebee,stroke:#c62828,color:#1b1b1b",
    "    classDef finding stroke-width:3px,stroke-dasharray:4 3",
)


def _text(value: str) -> str:
    """Text für Mermaid-Labels in Anführungszeichen."""
    return value.replace('"', "#quot;").replace("\n", " ")


def _token(value: str) -> str:
    """Bezeichner für erDiagram (Entitäten, Attribute, Typen)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)


def _node_label(node: ViewNode) -> str:
    lines = [node.label]
    if node.sublabel:
        lines.append(node.sublabel)
    mark = marker(node.status, node.finding)
    if mark:
        lines.append(f"[{mark}]")
    return "<br/>".join(_text(line) for line in lines)


class MermaidRenderer:
    name = "mermaid"
    extension = "mmd"

    def render(self, view: ViewResult) -> str:
        lines = self._erd(view) if view.view.kind == "erd" else self._flow(view)
        header = [
            f"%% lotse render mermaid --view {view.view.name}",
            f"%% {view.workspace_name}: {view.view.title}",
        ]
        if view.view.description:
            header.append(f"%% {view.view.description}")
        return "\n".join(header + lines) + "\n"

    def _flow(self, view: ViewResult) -> list[str]:
        lines = ["flowchart LR"]
        for lane, lane_label in view.lanes():
            lines.append(f'    subgraph lane{lane}["{_text(lane_label)}"]')
            for n in (n for n in view.nodes if n.lane == lane):
                lines.append(f'        {safe_id(n.id)}["{_node_label(n)}"]')
            lines.append("    end")
        for e in view.edges:
            lines.append(f'    {safe_id(e.src)} -->|"{_text(e.label)}"| {safe_id(e.dst)}')
        lines.extend(CLASS_DEFS)
        by_class: dict[str, list[str]] = {}
        for n in view.nodes:
            by_class.setdefault(n.status or "draft", []).append(safe_id(n.id))
            if n.finding:
                by_class.setdefault("finding", []).append(safe_id(n.id))
        for cls in ("agreed", "draft", "conflict", "finding"):
            if cls in by_class:
                lines.append(f"    class {','.join(by_class[cls])} {cls}")
        return lines

    def _erd(self, view: ViewResult) -> list[str]:
        lines = ["erDiagram"]
        names = {n.id: _token(n.id.split(".", 1)[-1]) for n in view.nodes}
        for n in view.nodes:
            lines.append(f"    {names[n.id]} {{")
            for col in n.detail or []:
                keys = []
                if col.get("key"):
                    keys.append("PK")
                if col.get("references"):
                    keys.append("FK")
                key = f" {', '.join(keys)}" if keys else ""
                comment = f' "{_text(col["description"])}"' if col.get("description") else ""
                col_type = _token(col.get("type", "string"))
                lines.append(f"        {col_type} {_token(col['name'])}{key}{comment}")
            lines.append("    }")
        for e in view.edges:
            lines.append(f'    {names[e.src]} }}o--|| {names[e.dst]} : "{_text(e.label)}"')
        return lines
