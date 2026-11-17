"""Renderer: eine Sicht (:class:`lotse.views.ViewResult`) rein, eine Darstellung (Text) raus.

Live-Viewer, Archify und Mermaid sind Implementierungen derselben Schnittstelle
(Konzept, Prinzip 5). Renderer sind rein und deterministisch: gleiche Sicht, gleiche Bytes.
"""

from __future__ import annotations

import re
from typing import Protocol

from lotse.views import ViewResult

STATUS_LABEL = {"draft": "Entwurf", "conflict": "Konflikt", "agreed": "einig"}
FINDING_LABEL = {
    "error": "Fehler",
    "conflict": "Konflikt",
    "gap": "Lücke",
    "warn": "Warnung",
    "info": "Hinweis",
}


class RenderError(Exception):
    pass


class Renderer(Protocol):
    name: str
    extension: str

    def render(self, view: ViewResult) -> str: ...


def safe_id(node_id: str) -> str:
    """``<typ>.<slug>`` → ``<typ>-<slug>``; erfüllt ``^[a-zA-Z][a-zA-Z0-9_-]*$``.

    Eindeutig, weil eine lotse-ID genau einen Punkt hat und der Typ keinen Bindestrich.
    """
    out = re.sub(r"[^A-Za-z0-9_-]", "-", node_id)
    return out if out[:1].isalpha() else f"n-{out}"


def marker(status: str | None, finding: str | None) -> str | None:
    """Kurzer Text zu Status und Befund, damit Bedeutung nicht nur an Farbe hängt."""
    parts = []
    if status and status != "agreed":
        parts.append(STATUS_LABEL.get(status, status))
    if finding:
        label = FINDING_LABEL.get(finding, finding)
        if label not in parts:
            parts.append(label)
    return " · ".join(parts) or None


def get_renderer(name: str) -> Renderer:
    from lotse.render.archify import ArchifyRenderer
    from lotse.render.mermaid import MermaidRenderer

    renderers: dict[str, Renderer] = {"archify": ArchifyRenderer(), "mermaid": MermaidRenderer()}
    try:
        return renderers[name]
    except KeyError as exc:
        raise RenderError(f"Unbekannter Renderer {name!r}") from exc
