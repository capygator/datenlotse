"""Gemeinsame Bausteine für CLI-Untergruppen (``render``, ``gen``).

Untergruppen importieren von hier, nicht aus ``lotse.cli`` (sonst Importzyklus).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lotse.store.build import BuildResult, build
from lotse.store.workspace import WorkspaceError, find_workspace

OUT_DIR = "out"
"""Standard-Ausgabeordner, relativ zum Workspace (gitignored)."""

WorkspaceOpt = Annotated[
    Path | None,
    typer.Option(
        "--workspace",
        "-w",
        help="Workspace-Ordner. Standard: lotse.yaml im aktuellen Ordner oder darüber.",
    ),
]

OutOpt = Annotated[
    Path | None,
    typer.Option("--out", "-o", help="Ausgabeordner. Standard: <workspace>/out."),
]


def build_for_output(workspace: Path | None) -> BuildResult:
    """Index neu bauen; bei ``error``-Befunden abbrechen (Exit 1)."""
    try:
        root = find_workspace(workspace)
    except WorkspaceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    result = build(root)
    if result.has_errors:
        for f in result.findings:
            if f.severity == "error":
                typer.echo(f"ERROR {f.rule} {f.node_id or '-'} {f.message}", err=True)
        typer.echo("Abbruch: Workspace hat error-Befunde (lotse check).", err=True)
        raise typer.Exit(1)
    return result


def out_dir(result: BuildResult, out: Path | None) -> Path:
    return out if out is not None else result.workspace / OUT_DIR


def write_text(path: Path, text: str) -> None:
    """UTF-8, LF, byte-stabil."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
