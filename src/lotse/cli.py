"""Kommandozeile ``lotse``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from lotse.gen.cli import gen_app
from lotse.model.registry import SEVERITIES
from lotse.model.schema import write_schemas
from lotse.query import next_question, stage_status
from lotse.render.cli import render_app
from lotse.store.build import BuildResult, build
from lotse.store.workspace import WorkspaceError, find_workspace, init_workspace

app = typer.Typer(
    name="lotse",
    help="Anforderungen als deskriptiver Graph: YAML ist die Wahrheit, DuckDB der Index.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(render_app, name="render")
app.add_typer(gen_app, name="gen")

WorkspaceOpt = Annotated[
    Path | None,
    typer.Option(
        "--workspace",
        "-w",
        help="Workspace-Ordner. Standard: lotse.yaml im aktuellen Ordner oder darüber.",
    ),
]


def resolve_workspace(workspace: Path | None) -> Path:
    try:
        return find_workspace(workspace)
    except WorkspaceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


def _summary(result: BuildResult) -> str:
    name = result.loaded.config.name if result.loaded.config else result.workspace.name
    counts = ", ".join(f"{result.count(s)} {s}" for s in SEVERITIES)
    return f"{name}: {len(result.graph.nodes)} Knoten, {len(result.graph.edges)} Kanten · {counts}"


def _print_findings(result: BuildResult) -> None:
    for f in result.findings:
        typer.echo(f"{f.severity.upper():<8} {f.rule:<28} {f.node_id or '-':<34} {f.message}")


def run_build(workspace: Path | None, quiet: bool = False) -> BuildResult:
    result = build(resolve_workspace(workspace))
    if not quiet:
        _print_findings(result)
        typer.echo(_summary(result))
    return result


@app.command()
def init(
    name: Annotated[str, typer.Argument(help="Name des Workspaces, wird zum Ordnernamen.")],
    root: Annotated[Path, typer.Option(help="Elternordner der Workspaces.")] = Path("workspaces"),
) -> None:
    """Workspace mit Grundgerüst anlegen."""
    slug = name.strip().lower().replace(" ", "-")
    try:
        target = init_workspace(root / slug, name)
    except WorkspaceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Workspace angelegt: {target}")


@app.command("build")
def build_cmd(workspace: WorkspaceOpt = None) -> None:
    """YAML validieren, DuckDB neu bauen, Regeln ausführen."""
    run_build(workspace)


@app.command()
def check(workspace: WorkspaceOpt = None) -> None:
    """Wie build, Exit-Code 1 bei Befunden mit Severity error."""
    result = run_build(workspace)
    if result.has_errors:
        raise typer.Exit(1)


@app.command("next")
def next_cmd(
    workspace: WorkspaceOpt = None,
    as_json: Annotated[bool, typer.Option("--json", help="Ausgabe als JSON.")] = False,
) -> None:
    """Wichtigster offener Befund als Frage-Vorlage."""
    result = run_build(workspace, quiet=True)
    question = next_question(result.db_path)
    if as_json:
        typer.echo(
            json.dumps(question.to_dict() if question else None, ensure_ascii=False, indent=2)
        )
        return
    if question is None:
        typer.echo("Keine offenen Befunde.")
        return
    typer.echo(f"[{question.severity}] {question.rule} · {question.node_id or '-'}")
    if question.stage_label:
        typer.echo(f"Stufe: {question.stage_label}")
    if question.owner:
        typer.echo(f"Owner: {question.owner}")
    typer.echo(f"Frage: {question.question}")
    typer.echo(f"Offene Befunde insgesamt: {question.open_findings}")


@app.command()
def status(
    workspace: WorkspaceOpt = None,
    as_json: Annotated[bool, typer.Option("--json", help="Ausgabe als JSON.")] = False,
) -> None:
    """Fortschritt je Stufe und Zahl der Befunde."""
    result = run_build(workspace, quiet=True)
    stages = stage_status(result.db_path)
    if as_json:
        payload = [
            {
                "stage": s.stage,
                "label": s.label,
                "state": s.state,
                "nodes": s.nodes,
                "clean": s.clean,
                "progress": round(s.progress, 4),
                "findings": s.findings,
            }
            for s in stages
        ]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for s in stages:
        bar = "█" * round(s.progress * 10) + "░" * (10 - round(s.progress * 10))
        found = ", ".join(f"{n} {sev}" for sev, n in sorted(s.findings.items())) or "—"
        typer.echo(
            f"{s.label:<13} {bar} {s.clean:>3}/{s.nodes:<3} {s.state or '':<7} Befunde: {found}"
        )
    typer.echo(_summary(result))


@app.command()
def schema(
    out: Annotated[Path, typer.Option(help="Zielordner.")] = Path("schemas"),
) -> None:
    """JSON-Schemas aus dem Modell exportieren."""
    for path in write_schemas(out):
        typer.echo(str(path))


@app.command()
def serve(
    workspace: WorkspaceOpt = None,
    host: Annotated[str, typer.Option(help="Adresse des Webservers.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port des Webservers.")] = 8765,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Viewer im Browser öffnen.")
    ] = True,
) -> None:
    """Live-Viewer starten: Dateiwächter, Neubau bei Änderung, Graph per SSE."""
    import threading
    import webbrowser

    from lotse.serve import LotseServer, create_app

    ws = resolve_workspace(workspace)
    url = f"http://{host}:{port}/"
    typer.echo(f"lotse serve: {ws} → {url} (Strg+C beendet)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    LotseServer(create_app(ws), host=host, port=port).run()


@app.command()
def demo(
    replay_steps: Annotated[
        bool, typer.Option("--replay", help="Schritte gegen leeren Workspace abspielen.")
    ] = False,
    auto: Annotated[bool, typer.Option("--auto", help="Selbstlauf statt Leertaste.")] = False,
    delay: Annotated[float, typer.Option(help="Sekunden je Schritt bei --auto.")] = 4.0,
    record_video: Annotated[
        bool, typer.Option("--record", help="Video des Replays per Playwright (impliziert --auto).")
    ] = False,
    demo_dir: Annotated[Path, typer.Option(help="Ordner mit nordwind/ und replay/.")] = Path(
        "demo"
    ),
    target: Annotated[Path, typer.Option(help="Workspace für den Replay (wird geleert).")] = Path(
        "out/demo-replay"
    ),
    host: Annotated[str, typer.Option(help="Adresse des Webservers.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port des Webservers.")] = 8765,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Viewer im Browser öffnen.")
    ] = True,
) -> None:
    """Demo starten: Endzustand erkunden oder mit --replay die sechs Akte abspielen."""
    import time
    import webbrowser

    import click

    from lotse.demo.run import (
        REPLAY_MARKER,
        DemoPaths,
        play,
        prepare_target,
        record,
        running_server,
    )

    if not (demo_dir / "nordwind" / "lotse.yaml").is_file():
        typer.echo(f"Kein Demo-Ordner unter {demo_dir} (erwartet nordwind/lotse.yaml).", err=True)
        raise typer.Exit(2)
    if not replay_steps:
        serve(demo_dir / "nordwind", host, port, open_browser)
        return

    auto = auto or record_video
    paths = DemoPaths.from_demo_dir(demo_dir, target.resolve())
    try:
        prepare_target(paths.workspace)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    (paths.workspace / REPLAY_MARKER).touch()
    (paths.workspace / "lotse.yaml").write_text("name: Demo\n", encoding="utf-8")

    def wait() -> None:
        if auto:
            time.sleep(delay)
            return
        typer.echo("  [Leertaste] weiter · [q] beenden")
        if click.getchar() in ("q", "Q"):
            raise typer.Exit(0)

    with running_server(paths.workspace, host, port) as url:
        typer.echo(f"Viewer: {url}")
        stop_recording = None
        if record_video:
            try:
                stop_recording = record(url, Path("out/video"), delay)
            except RuntimeError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(2) from exc
        elif open_browser:
            webbrowser.open(url)
            time.sleep(1.5)
        results, failed_commands = play(paths, base_url=url, wait=wait, echo=typer.echo)
        if stop_recording:
            typer.echo(f"Video: {stop_recording()}")
    failed = [r.name for r in results if not r.ok]
    typer.echo("")
    if failed or failed_commands:
        if failed:
            typer.echo(f"✗ Abweichende Befunde in: {', '.join(failed)}")
        if failed_commands:
            typer.echo(f"✗ Fehlgeschlagene Befehle: {', '.join(failed_commands)}")
        raise typer.Exit(1)
    typer.echo(f"✓ {len(results)} Schritte, alle Befunde wie erwartet.")


if __name__ == "__main__":
    app()
