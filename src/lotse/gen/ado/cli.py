"""Befehl ``lotse gen ado``: Dry-Run (Standard) oder ``--apply``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from lotse.gen.ado.plan import LEVELS, Backlog, plan_backlog
from lotse.gen.ado.rest import RestWorkItemStore
from lotse.gen.ado.sync import AdoError, Process, SyncReport, Target, sync
from lotse.store.build import build
from lotse.store.workspace import WorkspaceError, find_workspace

PAT_ENV = ("AZURE_DEVOPS_EXT_PAT", "LOTSE_ADO_PAT")
OUT_REL = Path("out") / "ado" / "backlog.json"


def _pat() -> str | None:
    return next((v for v in (os.environ.get(n) for n in PAT_ENV) if v), None)


def preview(backlog: Backlog, target: Target) -> list[str]:
    depth: dict[str, int] = {}
    lines = []
    for item in backlog.items:
        level = depth.get(item.parent, -1) + 1 if item.parent else 0
        depth[item.key] = level
        label = "  " * level + target.type_of(item.level)
        lines.append(f"{label:<24} {item.title}  [{item.key}]")
    counts = {lvl: sum(1 for i in backlog.items if i.level == lvl) for lvl in LEVELS}
    summary = ", ".join(f"{n} {target.type_of(lvl)}" for lvl, n in counts.items())
    lines.append(f"{len(backlog.items)} Work Items ({summary}), Scope-Tag lotse-ws:{backlog.scope}")
    return lines


def report_lines(report: SyncReport) -> list[str]:
    lines = [f"angelegt   #{i:<6} {k}" for k, i in report.created]
    lines += [f"geändert   #{i:<6} {k} ({', '.join(f)})" for k, i, f in report.updated]
    lines += [f"verknüpft  #{i:<6} {k} → Parent #{p}" for k, i, p in report.linked]
    lines += [f"veraltet   #{i:<6} {k} (nicht mehr im Plan, unverändert)" for k, i in report.stale]
    lines += [f"Warnung: {w}" for w in report.warnings]
    lines.append(
        f"{len(report.created)} angelegt, {len(report.updated)} geändert, "
        f"{len(report.linked)} verknüpft, {len(report.unchanged)} unverändert, "
        f"{len(report.stale)} veraltet"
    )
    return lines


def ado(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace", "-w", help="Workspace-Ordner. Standard: lotse.yaml im/über cwd."
        ),
    ] = None,
    apply: Annotated[
        bool, typer.Option("--apply", help="Wirklich nach Azure DevOps schreiben.")
    ] = False,
    org: Annotated[
        str | None, typer.Option(help="ADO-Organisation (Name oder https://dev.azure.com/…).")
    ] = None,
    project: Annotated[str | None, typer.Option(help="ADO-Projekt (nur mit --apply).")] = None,
    process: Annotated[
        Process, typer.Option(help="Prozessvorlage: agile (User Story) oder scrum (PBI).")
    ] = "agile",
    area: Annotated[str | None, typer.Option(help="Area Path für neue Items.")] = None,
    iteration: Annotated[str | None, typer.Option(help="Iteration Path für neue Items.")] = None,
    scope: Annotated[
        str | None, typer.Option(help="Scope-Tag lotse-ws:<scope>. Standard: Ordnername.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option(help="Ziel der Plan-Datei. Standard: <ws>/out/ado/backlog.json.")
    ] = None,
) -> None:
    """Backlog (Epics, Features, Stories) als JSON planen; mit --apply nach ADO schreiben."""
    try:
        ws = find_workspace(workspace)
    except WorkspaceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    pat = _pat()
    if apply:
        missing = [n for n, v in (("--org", org), ("--project", project)) if not v]
        if not pat:
            missing.append(f"PAT in {' oder '.join(PAT_ENV)}")
        if missing:
            typer.echo(f"--apply braucht: {', '.join(missing)}. Nichts geschrieben.", err=True)
            raise typer.Exit(2)

    result = build(ws)
    if result.has_errors:
        typer.echo(
            f"Workspace hat {result.count('error')} Fehler; erst `lotse check` grün machen.",
            err=True,
        )
        raise typer.Exit(1)

    target = Target(process=process, area=area, iteration=iteration)
    try:
        backlog = plan_backlog(result, scope or ws.name)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    path = out or ws / OUT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(backlog.to_json().encode("utf-8"))

    for line in preview(backlog, target):
        typer.echo(line)
    typer.echo(f"Plan: {path}")

    if not apply:
        typer.echo("Dry-Run: nichts nach Azure DevOps geschrieben (--apply zum Schreiben).")
        return

    assert org and project and pat  # oben geprüft
    store = RestWorkItemStore(org, project, pat)
    typer.echo(f"Schreibe nach {store.project_url} (Prozess {process}) …")
    try:
        report = sync(backlog, store, target)
    except AdoError as exc:
        typer.echo(f"Fehler: {exc}", err=True)
        typer.echo("Bereits geschriebene Items werden beim nächsten Lauf erkannt.", err=True)
        raise typer.Exit(1) from exc
    for line in report_lines(report):
        typer.echo(line)
