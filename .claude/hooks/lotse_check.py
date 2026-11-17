"""PostToolUse-Hook: nach Schreibzugriffen in einem lotse-Workspace `lotse check` ausführen.

Liest das Hook-JSON von stdin. Liegt die geschriebene Datei in einem Workspace
(``lotse.yaml`` im Ordner oder darüber), läuft ``lotse check``. Bei Fehlern
Exit-Code 2: die Ausgabe geht als Rückmeldung an Claude.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def workspace_of(path: Path) -> Path | None:
    for candidate in (path.parent, *path.parents):
        if (candidate / "lotse.yaml").is_file():
            return candidate
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path or not str(file_path).endswith((".yaml", ".yml")):
        return 0
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(payload.get("cwd") or ".") / path
    ws = workspace_of(path.resolve())
    if ws is None:
        return 0
    result = subprocess.run(
        ["uv", "run", "--quiet", "lotse", "check", "-w", str(ws)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return 0
    print(f"lotse check meldet Fehler in {ws}:\n{result.stdout}{result.stderr}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
