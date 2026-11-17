"""PostToolUse-Hook aus .claude/hooks: lotse check nach YAML-Schreibzugriffen."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from conftest import NORDWIND, REPO

HOOK = REPO / ".claude" / "hooks" / "lotse_check.py"


def _run(file_path: Path) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(file_path)}})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )


def test_hook_ignores_files_outside_workspace(tmp_path: Path) -> None:
    assert _run(tmp_path / "notiz.yaml").returncode == 0
    assert _run(REPO / "README.md").returncode == 0


def test_hook_reports_errors_with_exit_2(tmp_path: Path) -> None:
    ws = tmp_path / "nw"
    shutil.copytree(NORDWIND, ws, ignore=shutil.ignore_patterns(".lotse"))
    target = ws / "measures" / "umsatz.yaml"
    assert _run(target).returncode == 0
    target.write_text(target.read_text().replace("table.fact_faktura", "table.weg"))
    result = _run(target)
    assert result.returncode == 2
    assert "dangling_reference" in result.stderr
