"""Liest alle YAML-Dateien eines Workspaces und validiert sie gegen das Modell."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from lotse.model.entities import WorkspaceConfig
from lotse.model.finding import Finding
from lotse.model.registry import ENTITY_TYPES, EntityType
from lotse.store.workspace import CONFIG_FILE


@dataclass(frozen=True)
class LoadedEntity:
    type: EntityType
    model: BaseModel
    file: str

    @property
    def id(self) -> str:
        value = getattr(self.model, "id")  # noqa: B009 - BaseModel kennt id nicht statisch
        assert isinstance(value, str)
        return value


@dataclass
class LoadResult:
    workspace: Path
    config: WorkspaceConfig | None
    entities: list[LoadedEntity] = field(default_factory=list)
    problems: list[Finding] = field(default_factory=list)


def _schema_error(message: str, node_id: str | None = None) -> Finding:
    return Finding("schema", "error", node_id, message)


def _read_yaml(path: Path, rel: str, problems: list[Finding]) -> object | None:
    """YAML lesen; Probleme landen in ``problems``, Rückgabe dann ``None``."""
    try:
        data: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        problems.append(_schema_error(f"{rel}: Datei fehlt"))
        return None
    except yaml.YAMLError as exc:
        problems.append(_schema_error(f"{rel}: kein gültiges YAML ({exc})"))
        return None
    if data is None:
        problems.append(_schema_error(f"{rel}: Datei enthält keine Daten"))
    return data


def _format_validation(rel: str, exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(Datei)"
        parts.append(f"{loc}: {err['msg']}")
    return f"{rel}: " + "; ".join(parts)


def load_workspace(workspace: Path) -> LoadResult:
    workspace = workspace.resolve()
    problems: list[Finding] = []

    config: WorkspaceConfig | None = None
    raw_config = _read_yaml(workspace / CONFIG_FILE, CONFIG_FILE, problems)
    if raw_config is not None:
        try:
            config = WorkspaceConfig.model_validate(raw_config)
        except ValidationError as exc:
            problems.append(_schema_error(_format_validation(CONFIG_FILE, exc)))

    result = LoadResult(workspace=workspace, config=config, problems=problems)
    for etype in ENTITY_TYPES:
        folder = workspace / etype.folder
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.yaml")):
            rel = path.relative_to(workspace).as_posix()
            raw = _read_yaml(path, rel, problems)
            if raw is None:
                continue
            raw_id = raw.get("id") if isinstance(raw, dict) else None
            node_id = raw_id if isinstance(raw_id, str) else None
            try:
                model = etype.model.model_validate(raw)
            except ValidationError as exc:
                problems.append(_schema_error(_format_validation(rel, exc), node_id))
                continue
            entity = LoadedEntity(etype, model, rel)
            expected_slug = path.stem
            actual_slug = entity.id.split(".", 1)[1]
            if actual_slug != expected_slug:
                problems.append(
                    _schema_error(
                        f"{rel}: id {entity.id} passt nicht zum Dateinamen "
                        f"(erwartet {etype.name}.{expected_slug})",
                        entity.id,
                    )
                )
                continue
            # Typpräfix (Modell) + Dateiname (Ordner) machen die id eindeutig.
            result.entities.append(entity)
    return result
