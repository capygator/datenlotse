"""Export der JSON-Schemas aus den Pydantic-Modellen (einzige Quelle der Wahrheit)."""

from __future__ import annotations

import json
from pathlib import Path

from lotse.model.entities import WorkspaceConfig
from lotse.model.registry import ENTITY_TYPES


def schemas() -> dict[str, str]:
    """Dateiname -> JSON-Text, deterministisch formatiert."""
    out: dict[str, str] = {}
    out["workspace.schema.json"] = _dump(WorkspaceConfig.model_json_schema())
    for t in ENTITY_TYPES:
        out[f"{t.name}.schema.json"] = _dump(t.model.model_json_schema())
    return out


def write_schemas(target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in schemas().items():
        path = target / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def _dump(schema: dict[str, object]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
