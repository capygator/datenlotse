"""Workspace finden und anlegen."""

from __future__ import annotations

from pathlib import Path

import yaml

from lotse.model.registry import ENTITY_TYPES, STAGES

CONFIG_FILE = "lotse.yaml"
INDEX_DIR = ".lotse"
INDEX_FILE = "lotse.duckdb"


class WorkspaceError(Exception):
    pass


def find_workspace(start: Path | None = None) -> Path:
    """Sucht ab ``start`` (Standard: aktuelles Verzeichnis) aufwärts nach ``lotse.yaml``."""
    here = (start or Path.cwd()).resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_FILE).is_file():
            return candidate
    raise WorkspaceError(f"Kein Workspace gefunden: keine {CONFIG_FILE} in {here} oder darüber.")


def index_path(workspace: Path) -> Path:
    return workspace / INDEX_DIR / INDEX_FILE


def init_workspace(target: Path, name: str) -> Path:
    """Legt einen leeren Workspace mit Grundgerüst an."""
    if target.exists() and any(target.iterdir()):
        raise WorkspaceError(f"{target} existiert bereits und ist nicht leer.")
    target.mkdir(parents=True, exist_ok=True)
    config = {
        "name": name,
        "platform": "fabric",
        "stages": {t.name: ("active" if t.stage == 1 else "open") for t in STAGES},
    }
    (target / CONFIG_FILE).write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    for t in ENTITY_TYPES:
        folder = target / t.folder
        folder.mkdir(exist_ok=True)
        (folder / ".gitkeep").touch()
    return target
