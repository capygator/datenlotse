"""Replay-Engine: spielt ``demo/replay/steps/*.yaml`` gegen einen leeren Workspace ab.

Ein Schritt kopiert Dateien aus dem Endzustand (``copy``), schreibt Zwischenstände
(``write``, Mapping → YAML) oder löscht Dateien (``delete``). Nach jedem Schritt wird
neu gebaut und die Befundliste mit ``expect`` verglichen. Die Schritte sind damit
zugleich der End-to-End-Test.
"""

from __future__ import annotations

import shutil
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from lotse.model.finding import Finding
from lotse.store.build import BuildResult, build


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: str
    node: str | None = None


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    act: int
    title: str
    question: str
    answer: str
    by: str | None = None
    command: str | None = None
    commands: list[str] = []
    copy_files: list[str] = []
    write: dict[str, Any] = {}
    delete: list[str] = []
    expect: list[Expected] = []

    @classmethod
    def load(cls, path: Path) -> Step:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if "copy" in raw:
            raw["copy_files"] = raw.pop("copy")
        return cls.model_validate(raw)


@dataclass(frozen=True)
class StepResult:
    index: int
    name: str
    step: Step
    build: BuildResult
    missing: list[tuple[str, str | None]]
    unexpected: list[tuple[str, str | None]]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.unexpected


def load_steps(steps_dir: Path) -> list[tuple[str, Step]]:
    return [(p.stem, Step.load(p)) for p in sorted(steps_dir.glob("*.yaml"))]


def dump_yaml(data: object) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)


def reset_workspace(target: Path) -> None:
    """Leert den Workspace, ohne den Ordner selbst zu löschen (Dateiwächter bleibt gültig)."""
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.name == ".lotse-replay":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def apply_step(step: Step, workspace: Path, final_dir: Path) -> list[str]:
    """Wendet einen Schritt an und liefert die geänderten Pfade (relativ, sortiert)."""
    changed: list[str] = []
    for rel in step.copy_files:
        dst = workspace / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(final_dir / rel, dst)
        changed.append(rel)
    for rel, content in step.write.items():
        dst = workspace / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(dump_yaml(content), encoding="utf-8")
        changed.append(rel)
    for rel in step.delete:
        (workspace / rel).unlink(missing_ok=True)
        changed.append(rel)
    return sorted(set(changed))


def compare(
    findings: list[Finding], expected: list[Expected]
) -> tuple[list[tuple[str, str | None]], list[tuple[str, str | None]]]:
    actual = Counter((f.rule, f.node_id) for f in findings)
    wanted = Counter((e.rule, e.node) for e in expected)
    missing = sorted((wanted - actual).elements(), key=str)
    unexpected = sorted((actual - wanted).elements(), key=str)
    return missing, unexpected


def replay(
    steps_dir: Path,
    final_dir: Path,
    workspace: Path,
    before_step: Callable[[int, str, Step], None] | None = None,
    after_step: Callable[[StepResult], None] | None = None,
) -> list[StepResult]:
    """Spielt alle Schritte ab. Der Workspace wird vorher geleert."""
    reset_workspace(workspace)
    results: list[StepResult] = []
    for index, (name, step) in enumerate(load_steps(steps_dir)):
        if before_step:
            before_step(index, name, step)
        apply_step(step, workspace, final_dir)
        result = build(workspace)
        missing, unexpected = compare(result.findings, step.expect)
        step_result = StepResult(index, name, step, result, missing, unexpected)
        results.append(step_result)
        if after_step:
            after_step(step_result)
    return results


def workspace_files(workspace: Path) -> dict[str, Any]:
    """Alle YAML-Dateien eines Workspaces, geparst (für den Vergleich mit dem Endzustand)."""
    return {
        p.relative_to(workspace).as_posix(): yaml.safe_load(p.read_text(encoding="utf-8"))
        for p in sorted(workspace.rglob("*.yaml"))
        if ".lotse" not in p.parts
    }
