"""Pydantic-Modelle der Workspace-Entitäten.

Die Feldreihenfolge der Modelle ist die kanonische Schlüsselreihenfolge in YAML.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SLUG = r"[a-z0-9][a-z0-9_-]*"


def _ref(prefix: str) -> Any:
    return Field(pattern=rf"^{prefix}\.{SLUG}$")


DecisionId = Annotated[str, _ref("decision")]
ProductId = Annotated[str, _ref("product")]
MeasureId = Annotated[str, _ref("measure")]
DimensionId = Annotated[str, _ref("dimension")]
TableId = Annotated[str, _ref("table")]
SourceId = Annotated[str, _ref("source")]
StakeholderId = Annotated[str, _ref("stakeholder")]
StatementId = Annotated[str, _ref("statement")]
QuestionId = Annotated[str, _ref("question")]
AnyId = Annotated[
    str,
    Field(
        pattern=rf"^(decision|product|measure|dimension|table|source|stakeholder|statement|question)\.{SLUG}$"
    ),
]

Status = Literal["draft", "agreed", "conflict"]
StageName = Literal["decision", "product", "measure", "dimension", "table", "source"]
StageState = Literal["open", "active", "done"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Staged(_Model):
    """Gemeinsame Felder der sechs Stufen-Entitäten."""

    name: str
    description: str | None = None
    status: Status = "draft"
    owner: StakeholderId | None = None
    statement: StatementId | None = None


class Decision(_Staged):
    id: DecisionId


class Product(_Staged):
    id: ProductId
    kind: Literal["report", "semantic_model"] = "semantic_model"
    serves: list[DecisionId] = []
    measures: list[MeasureId] = []


class Definition(_Model):
    by: StakeholderId
    text: str
    statement: StatementId | None = None


class QualityRule(_Model):
    rule: str
    description: str | None = None


class Measure(_Staged):
    id: MeasureId
    unit: str | None = None
    grain: list[DimensionId] = []
    definitions: list[Definition] = []
    time_logic: str | None = None
    serves: list[DecisionId] = []
    from_tables: list[TableId] = []
    quality: list[QualityRule] = []


class Dimension(_Staged):
    id: DimensionId
    hierarchy: list[str] = []
    from_tables: list[TableId] = []


ColumnType = Literal["string", "int64", "decimal", "double", "date", "datetime", "boolean"]


class Column(_Model):
    name: str
    type: ColumnType = "string"
    description: str | None = None
    key: bool = False
    references: TableId | None = None


class Table(_Staged):
    id: TableId
    kind: Literal["fact", "dimension"]
    from_sources: list[SourceId] = []
    columns: list[Column] = []


class Source(_Staged):
    id: SourceId
    system: str
    objects: list[str] = []


class Stakeholder(_Model):
    id: StakeholderId
    name: str
    role: str | None = None
    description: str | None = None


class Statement(_Model):
    id: StatementId
    by: StakeholderId
    text: str
    context: str | None = None


class Question(_Model):
    id: QuestionId
    text: str
    status: Literal["open", "answered"] = "open"
    owner: StakeholderId | None = None
    statement: StatementId | None = None
    about: list[AnyId] = []
    answer: StatementId | None = None


class WorkspaceConfig(_Model):
    name: str
    platform: Literal["fabric"] = "fabric"
    description: str | None = None
    stages: dict[StageName, StageState] = {}


Entity = (
    Decision | Product | Measure | Dimension | Table | Source | Stakeholder | Statement | Question
)
