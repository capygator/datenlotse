"""``lotse render <mermaid|archify> --view <name>``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from lotse.cli_common import OutOpt, WorkspaceOpt, build_for_output, out_dir, write_text
from lotse.render import RenderError, get_renderer
from lotse.views import ViewError, get_view, list_views, run_view

render_app = typer.Typer(
    help="Statische Sicht erzeugen: Sicht (src/lotse/views/*.sql) → Darstellung.",
    no_args_is_help=True,
)

ViewOpt = Annotated[str, typer.Option("--view", "-v", help="Name der Sicht, z. B. lineage.")]


def render_view(
    renderer_name: str, view_name: str, workspace: Path | None, out: Path | None
) -> Path:
    result = build_for_output(workspace)
    renderer = get_renderer(renderer_name)
    try:
        view = run_view(result.db_path, get_view(view_name))
        text = renderer.render(view)
    except (ViewError, RenderError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    target = out_dir(result, out) / f"{view_name}.{renderer.extension}"
    write_text(target, text)
    typer.echo(str(target))
    return target


@render_app.command()
def mermaid(view: ViewOpt, workspace: WorkspaceOpt = None, out: OutOpt = None) -> None:
    """Mermaid-Diagramm nach <out>/<view>.mmd."""
    render_view("mermaid", view, workspace, out)


@render_app.command()
def archify(view: ViewOpt, workspace: WorkspaceOpt = None, out: OutOpt = None) -> None:
    """Archify-JSON (Data Flow bzw. ERD) nach <out>/<view>.json."""
    render_view("archify", view, workspace, out)


@render_app.command("views")
def views_cmd() -> None:
    """Verfügbare Sichten auflisten."""
    for v in list_views():
        typer.echo(f"{v.name:<16} {v.kind:<5} {v.title}")
