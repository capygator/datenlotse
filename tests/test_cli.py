from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from conftest import NORDWIND
from typer.testing import CliRunner

from lotse.cli import app
from lotse.model.registry import ENTITY_TYPES

runner = CliRunner()


def test_init_creates_skeleton_that_builds(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "Neues Projekt", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    ws = tmp_path / "neues-projekt"
    assert (ws / "lotse.yaml").is_file()
    for t in ENTITY_TYPES:
        assert (ws / t.folder / ".gitkeep").is_file()
    check = runner.invoke(app, ["check", "-w", str(ws)])
    assert check.exit_code == 0, check.output
    assert "0 Knoten" in check.output


def test_init_refuses_non_empty_target(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "datei").write_text("a")
    result = runner.invoke(app, ["init", "x", "--root", str(tmp_path)])
    assert result.exit_code == 1


def _nordwind(tmp_path: Path) -> Path:
    target = tmp_path / "nordwind"
    shutil.copytree(NORDWIND, target, ignore=shutil.ignore_patterns(".lotse"))
    return target


def test_check_exit_code_follows_errors(tmp_path: Path) -> None:
    ws = _nordwind(tmp_path)
    assert runner.invoke(app, ["check", "-w", str(ws)]).exit_code == 0
    path = ws / "measures" / "umsatz.yaml"
    path.write_text(path.read_text().replace("table.fact_faktura", "table.fact_gibtsnicht"))
    result = runner.invoke(app, ["check", "-w", str(ws)])
    assert result.exit_code == 1
    assert "dangling_reference" in result.output


def test_build_never_fails_on_findings(tmp_path: Path) -> None:
    ws = _nordwind(tmp_path)
    (ws / "measures" / "umsatz.yaml").write_text("id: [kaputt")
    assert runner.invoke(app, ["build", "-w", str(ws)]).exit_code == 0


def test_workspace_found_from_subfolder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _nordwind(tmp_path)
    monkeypatch.chdir(ws / "measures")
    assert runner.invoke(app, ["check"]).exit_code == 0


def test_missing_workspace_exit_2(tmp_path: Path) -> None:
    assert runner.invoke(app, ["check", "-w", str(tmp_path)]).exit_code == 2


def test_next_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["next", "--json", "-w", str(_nordwind(tmp_path))])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["rule"] == "table_without_source"
    assert data["node_id"] == "table.fact_lieferzusage"
    assert data["stage"] == "table"
    assert "Quellsystem" in data["question"]
    assert {"kind": "about", "id": "question.liefertermin-quelle", "direction": "in"} in data[
        "related"
    ]


def test_next_prefers_errors_then_earlier_stage(tmp_path: Path) -> None:
    ws = _nordwind(tmp_path)
    p = ws / "measures" / "umsatz.yaml"
    p.write_text(p.read_text().replace("owner: stakeholder.controlling-leitung\n", ""))
    data = json.loads(runner.invoke(app, ["next", "--json", "-w", str(ws)]).output)
    assert (data["rule"], data["node_id"]) == ("missing_owner", "measure.umsatz")
    p.write_text(p.read_text().replace("table.fact_faktura", "table.weg"))
    data = json.loads(runner.invoke(app, ["next", "--json", "-w", str(ws)]).output)
    assert data["rule"] == "dangling_reference"


def test_status_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["status", "--json", "-w", str(_nordwind(tmp_path))])
    stages = {s["stage"]: s for s in json.loads(result.output)}
    assert list(stages) == ["decision", "product", "measure", "dimension", "table", "source"]
    assert stages["table"]["nodes"] == 9
    assert stages["table"]["clean"] == 8
    assert stages["table"]["findings"] == {"gap": 1}
    assert stages["measure"]["progress"] == 1.0
