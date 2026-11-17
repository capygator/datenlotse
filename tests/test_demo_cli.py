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
    out = tmp_path / "replay" / "out"
    assert (out / "ado" / "backlog.json").is_file()
    assert (out / "lineage.mmd").is_file()
    assert (out / "tmdl" / "auftragsbestand-cockpit").is_dir()
    assert "Exit-Code" not in result.output


def test_replay_refuses_foreign_non_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "wichtig"
    target.mkdir()
    (target / "notizen.txt").write_text("nicht löschen")
    result = runner.invoke(
        app,
        [
            "demo",
            "--replay",
            "--auto",
            "--no-open",
            "--demo-dir",
            str(REPO / "demo"),
            "--target",
            str(target),
            "--port",
            str(_free_port()),
        ],
    )
    assert result.exit_code == 2
    assert (target / "notizen.txt").read_text() == "nicht löschen"


def test_demo_without_demo_dir_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["demo", "--demo-dir", str(tmp_path)])
    assert result.exit_code == 2
