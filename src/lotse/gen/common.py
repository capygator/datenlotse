"""Gemeinsame Hilfen der Generatoren."""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from lotse.model.entities import Dimension, Measure, Product, Table
from lotse.store.build import BuildResult

T = TypeVar("T", bound=BaseModel)

LINEAGE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:lotse")
"""Namensraum für deterministische UUIDs (lineageTags, Beziehungsnamen)."""


def stable_uuid(key: str) -> str:
    return str(uuid.uuid5(LINEAGE_NAMESPACE, key))


def slug(entity_id: str) -> str:
    return entity_id.split(".", 1)[1]


def ident(value: str) -> str:
    """Bezeichner aus ``[A-Za-z0-9_]``, beginnt nicht mit einer Ziffer."""
    out = re.sub(r"[^A-Za-z0-9_]", "_", value)
    return out if re.match(r"[A-Za-z_]", out) else f"_{out}"


@dataclass
class Index:
    """Typisierter Zugriff auf die geladenen Entitäten eines Builds."""

    result: BuildResult

    def get(self, entity_id: str, model: type[T]) -> T | None:
        for e in self.result.loaded.entities:
            if e.id == entity_id and isinstance(e.model, model):
                return e.model
        return None

    def all(self, model: type[T]) -> list[T]:
        items = [e.model for e in self.result.loaded.entities if isinstance(e.model, model)]
        return sorted(items, key=lambda m: str(getattr(m, "id", "")))

    @property
    def workspace_name(self) -> str:
        cfg = self.result.loaded.config
        return cfg.name if cfg else self.result.workspace.name


def key_column(table: Table) -> str | None:
    """Die einzige Schlüsselspalte einer Tabelle, sonst ``None``."""
    keys = [c.name for c in table.columns if c.key]
    return keys[0] if len(keys) == 1 else None


def product_scope(index: Index, product: Product) -> tuple[list[Measure], list[Table]]:
    """Kennzahlen des Produkts und alle Tabellen, die sie brauchen.

    Tabellen = ``from_tables`` der Kennzahlen, plus Tabellen der Grain-Dimensionen, plus per
    ``references`` erreichbare Tabellen. Reihenfolge: Kennzahlen wie im Produkt, Tabellen nach id.
    """
    measures = [m for mid in product.measures if (m := index.get(mid, Measure)) is not None]
    wanted: set[str] = set()
    for m in measures:
        wanted.update(m.from_tables)
        for dim_id in m.grain:
            dim = index.get(dim_id, Dimension)
            if dim is not None:
                wanted.update(dim.from_tables)
    queue = sorted(wanted)
    while queue:
        table = index.get(queue.pop(), Table)
        for col in table.columns if table else []:
            if col.references and col.references not in wanted:
                wanted.add(col.references)
                queue.append(col.references)
    tables = [t for tid in sorted(wanted) if (t := index.get(tid, Table)) is not None]
    return measures, tables


def write_tree(target: Path, files: dict[str, str], stale_glob: str | None = None) -> list[Path]:
    """Dateien (UTF-8, LF) schreiben; vorher nur Generator-eigene Altlasten entfernen.

    Entfernt werden die obersten Einträge, die gleich neu geschrieben werden (z. B. ein
    Projektordner je Produkt), sowie Dateien in ``target``, die auf ``stale_glob`` passen.
    Andere Inhalte von ``target`` bleiben unangetastet.
    """
    doomed = {target / rel.split("/", 1)[0] for rel in files}
    if stale_glob and target.is_dir():
        doomed.update(target.glob(stale_glob))
    for path in sorted(doomed):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
    written = []
    for rel in sorted(files):
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(files[rel].encode("utf-8"))
        written.append(path)
    return written
