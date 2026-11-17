"""Entitätstypen, Ordner und Stufenreihenfolge."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from lotse.model.entities import (
    Decision,
    Dimension,
    Measure,
    Product,
    Question,
    Source,
    Stakeholder,
    Statement,
    Table,
)


@dataclass(frozen=True)
class EntityType:
    name: str
    folder: str
    model: type[BaseModel]
    label: str
    stage: int | None = None


ENTITY_TYPES: tuple[EntityType, ...] = (
    EntityType("decision", "decisions", Decision, "Entscheidung", 1),
    EntityType("product", "products", Product, "Datenprodukt", 2),
    EntityType("measure", "measures", Measure, "Kennzahl", 3),
    EntityType("dimension", "dimensions", Dimension, "Dimension", 4),
    EntityType("table", "tables", Table, "Tabelle", 5),
    EntityType("source", "sources", Source, "Quelle", 6),
    EntityType("stakeholder", "stakeholders", Stakeholder, "Stakeholder"),
    EntityType("statement", "statements", Statement, "Aussage"),
    EntityType("question", "questions", Question, "Offene Frage"),
)

BY_NAME: dict[str, EntityType] = {t.name: t for t in ENTITY_TYPES}
STAGES: tuple[EntityType, ...] = tuple(t for t in ENTITY_TYPES if t.stage is not None)

SEVERITIES: tuple[str, ...] = ("error", "conflict", "gap", "warn", "info")
"""Severities, wichtigste zuerst."""
