from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from lotse.model.finding import Finding
from lotse.store.build import build

REPO = Path(__file__).resolve().parent.parent
NORDWIND = REPO / "demo" / "nordwind"

Files = dict[str, Any]

BASE: Files = {
    "lotse.yaml": {"name": "Test"},
    "stakeholders/owner.yaml": {"id": "stakeholder.owner", "name": "Owner"},
    "statements/0001.yaml": {"id": "statement.0001", "by": "stakeholder.owner", "text": "A"},
    "decisions/d.yaml": {"id": "decision.d", "name": "D"},
    "products/p.yaml": {
        "id": "product.p",
        "name": "P",
        "owner": "stakeholder.owner",
        "serves": ["decision.d"],
        "measures": ["measure.m"],
    },
    "measures/m.yaml": {
        "id": "measure.m",
        "name": "M",
        "owner": "stakeholder.owner",
        "grain": ["dimension.k"],
        "definitions": [
            {"by": "stakeholder.owner", "text": "Summe X", "statement": "statement.0001"}
        ],
        "serves": ["decision.d"],
        "from_tables": ["table.t"],
    },
    "dimensions/k.yaml": {"id": "dimension.k", "name": "K", "from_tables": ["table.t"]},
    "tables/t.yaml": {"id": "table.t", "name": "T", "kind": "fact", "from_sources": ["source.s"]},
    "sources/s.yaml": {"id": "source.s", "name": "S", "system": "ERP"},
}


def write_workspace(root: Path, files: Files) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(yaml.safe_dump(content, sort_keys=False, allow_unicode=True))
    return root


@pytest.fixture
def base() -> Files:
    return copy.deepcopy(BASE)


@pytest.fixture
def run(tmp_path: Path) -> Callable[[Files], list[Finding]]:
    def _run(files: Files) -> list[Finding]:
        return build(write_workspace(tmp_path / "ws", files)).findings

    return _run
