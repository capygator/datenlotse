"""``lotse demo``: Replay mit Live-Viewer, Einblendung von Frage und Antwort, Selbstlauf."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from lotse.demo.replay import Step, StepResult, replay
from lotse.serve import create_app


@dataclass(frozen=True)
class DemoPaths:
    steps: Path
    final: Path
    workspace: Path

    @classmethod
    def from_demo_dir(cls, demo_dir: Path, workspace: Path) -> DemoPaths:
        return cls(demo_dir / "replay" / "steps", demo_dir / "nordwind", workspace)


@contextmanager
def running_server(workspace: Path, host: str, port: int) -> Iterator[str]:
    """Startet den Viewer-Server in einem Thread und wartet, bis er antwortet."""
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(workspace),
            host=host,
            port=port,
            log_level="warning",
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://{host}:{port}/"
    deadline = time.monotonic() + 10
    while True:
        try:
            with urllib.request.urlopen(url + "api/graph", timeout=1):
                break
        except OSError:
            if time.monotonic() > deadline or not thread.is_alive():
                server.should_exit = True
                raise RuntimeError(f"Viewer-Server unter {url} startet nicht") from None
            time.sleep(0.1)
    try:
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def post_caption(base_url: str, step: Step | None) -> None:
    body = (
        {}
        if step is None
        else {
            "text": f"Akt {step.act}: {step.title}",
            "question": step.question,
            "answer": step.answer,
        }
    )
    req = urllib.request.Request(
        base_url + "api/caption",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5):
        pass


def run_step_commands(step: Step, workspace: Path, echo: Callable[[str], None]) -> list[str]:
    """Führt ``lotse …``-Befehle eines Schritts aus (z. B. Generatoren in Akt 6).

    Liefert die fehlgeschlagenen Befehle.
    """
    failed: list[str] = []
    for command in step.commands:
        parts = command.split()
        if not parts or parts[0] != "lotse":
            continue
        echo(f"  $ {command}")
        proc = subprocess.run(
            [sys.executable, "-m", "lotse.cli", *parts[1:], "-w", str(workspace)],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in (proc.stdout + proc.stderr).strip().splitlines()[-3:]:
            echo(f"    {line}")
        if proc.returncode != 0:
            echo(f"    ✗ Exit-Code {proc.returncode}")
            failed.append(command)
    return failed


def play(
    paths: DemoPaths,
    *,
    base_url: str | None,
    wait: Callable[[], None],
    echo: Callable[[str], None],
    run_commands: bool = True,
) -> tuple[list[StepResult], list[str]]:
    """Spielt alle Schritte ab; ``wait`` blockiert zwischen den Schritten.

    Liefert die Schrittergebnisse und die fehlgeschlagenen Befehle.
    """
    failed_commands: list[str] = []

    def before(index: int, name: str, step: Step) -> None:
        echo("")
        echo(f"── Akt {step.act} · {step.title} ({name})")
        echo(f"  Frage:   {step.question}")
        who = f" ({step.by})" if step.by else ""
        echo(f"  Antwort{who}: {step.answer}")
        if step.command:
            echo(f"  Moderator: {step.command}")
        if base_url:
            post_caption(base_url, step)

    def after(result: StepResult) -> None:
        mark = "✓" if result.ok else "✗"
        counts = {s: result.build.count(s) for s in ("error", "conflict", "gap", "warn", "info")}
        summary = ", ".join(f"{n} {s}" for s, n in counts.items() if n) or "keine Befunde"
        echo(f"  {mark} Befunde wie erwartet: {summary}")
        if not result.ok:
            echo(f"    fehlend: {result.missing}")
            echo(f"    unerwartet: {result.unexpected}")
        if run_commands:
            failed_commands.extend(run_step_commands(result.step, paths.workspace, echo))
        wait()

    results = replay(
        paths.steps, paths.final, paths.workspace, before_step=before, after_step=after
    )
    return results, failed_commands


REPLAY_MARKER = ".lotse-replay"
"""Markerdatei: Nur so markierte (oder leere) Ordner darf der Replay leeren."""


def prepare_target(target: Path) -> None:
    """Prüft, ob ``target`` geleert werden darf, und markiert ihn als Replay-Ziel."""
    if target.exists() and any(target.iterdir()) and not (target / REPLAY_MARKER).exists():
        raise RuntimeError(
            f"{target} ist nicht leer und kein früheres Replay-Ziel; der Replay würde ihn leeren."
        )
    target.mkdir(parents=True, exist_ok=True)


def record(url: str, out: Path, duration_hint: float) -> Callable[[], Path]:
    """Startet ein Browser-Video per Playwright. Liefert eine Funktion zum Beenden."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Für --record wird Playwright gebraucht: "
            "uv pip install playwright && uv run playwright install chromium"
        ) from exc
    out.mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    browser = pw.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1600, "height": 900},
        record_video_dir=str(out),
        record_video_size={"width": 1600, "height": 900},
    )
    page = context.new_page()
    page.goto(url)
    page.wait_for_timeout(min(2000, duration_hint * 1000))

    def stop() -> Path:
        page.wait_for_timeout(1500)
        video = page.video
        context.close()
        browser.close()
        pw.stop()
        return Path(video.path()) if video else out

    return stop
