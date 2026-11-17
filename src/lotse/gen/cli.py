"""``lotse gen <odcs|tmdl|…>``.

Weitere Generatoren (z. B. ``ado``) als ``@gen_app.command()`` hier ergänzen. Jeder Befehl
baut vorher den Index neu (:func:`lotse.cli_common.build_for_output`) und schreibt in einen
eigenen Unterordner von ``<out>`` (Standard ``<workspace>/out``); vorher entfernt werden nur
die eigenen Altlasten (je Produkt der Projektordner bzw. ``*.odcs.yaml``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer

from lotse.cli_common import OutOpt, WorkspaceOpt, build_for_output, out_dir
from lotse.gen import odcs, tmdl
from lotse.gen.common import write_tree
from lotse.store.build import BuildResult

gen_app = typer.Typer(
    help="Artefakte aus dem Anforderungsgraphen generieren (idempotent, byte-stabil).",
    no_args_is_help=True,
)


def run_generator(
    folder: str,
    generate: Callable[[BuildResult], dict[str, str]],
    workspace: Path | None,
    out: Path | None,
    stale_glob: str | None = None,
) -> Path:
    result = build_for_output(workspace)
    try:
        files = generate(result)
    except (odcs.OdcsError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    target = out_dir(result, out) / folder
    for path in write_tree(target, files, stale_glob):
        typer.echo(str(path))
    return target


@gen_app.command("odcs")
def odcs_cmd(workspace: WorkspaceOpt = None, out: OutOpt = None) -> None:
    """Ein ODCS-v3.1.0-Contract je Datenprodukt nach <out>/odcs/, schema-validiert."""
    run_generator(odcs.FOLDER, odcs.generate, workspace, out, stale_glob="*.odcs.yaml")


@gen_app.command("tmdl")
def tmdl_cmd(workspace: WorkspaceOpt = None, out: OutOpt = None) -> None:
    """Power-BI-Projekt mit TMDL-Modell je Datenprodukt nach <out>/tmdl/<produkt>/."""
    run_generator(tmdl.FOLDER, tmdl.generate, workspace, out)
