"""``lotse demo --replay --auto`` läuft offline durch (Abnahme M3)."""

from __future__ import annotations

import socket
from pathlib import Path

from conftest import REPO
from typer.testing import CliRunner

from lotse.cli import app

runner = CliRunner()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_replay_auto_runs_through_with_viewer(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "demo",
            "--replay",
            "--auto",
            "--delay",
            "0",
            "--no-open",
            "--demo-dir",
            str(REPO / "demo"),
            "--target",
            str(tmp_path / "replay"),
            "--port",
            str(_free_port()),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "✓ 9 Schritte, alle Befunde wie erwartet." in result.output
    assert "Akt 3 · Konflikt" in result.output
    assert (tmp_path / "replay" / "out" / "odcs").is_dir()
    assert (tmp_path / "replay" / "out" / "ado" / "backlog.json").is_file()


def test_demo_without_demo_dir_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["demo", "--demo-dir", str(tmp_path)])
    assert result.exit_code == 2
