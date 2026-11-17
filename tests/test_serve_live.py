"""Ende-zu-Ende gegen einen echten uvicorn-Server: Datei ändern → SSE-Ereignis."""

from __future__ import annotations

import json
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
import pytest
import uvicorn
from conftest import NORDWIND

from lotse.serve import create_app
from lotse.serve.app import Hub

LATENCY_BUDGET_S = 2.0


@dataclass
class Live:
    url: str
    workspace: Path
    hub: Hub


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def live(tmp_path: Path) -> Iterator[Live]:
    ws = tmp_path / "nordwind"
    shutil.copytree(NORDWIND, ws, ignore=shutil.ignore_patterns(".lotse"))
    app = create_app(ws)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    hub: Hub = app.state.hub
    deadline = time.monotonic() + 10
    while not (server.started and hub.watching.is_set()):
        assert time.monotonic() < deadline, "Server/Wächter nicht bereit"
        time.sleep(0.02)
    yield Live(f"http://127.0.0.1:{port}", ws, hub)
    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive(), "Server hängt beim Beenden"


class EventReader:
    def __init__(self, response: httpx2.Response) -> None:
        self._lines = response.iter_lines()

    def next(self) -> tuple[str, dict[str, Any]]:
        kind, data = "message", ""
        for line in self._lines:
            if line.startswith("event:"):
                kind = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
            elif line == "" and data:
                return kind, json.loads(data)
        raise AssertionError("Stream beendet")


def _stream(live: Live) -> Any:
    timeout = httpx2.Timeout(5.0, read=LATENCY_BUDGET_S + 3)
    return httpx2.stream("GET", f"{live.url}/api/events", timeout=timeout)


def test_file_change_arrives_as_diff_within_budget(live: Live) -> None:
    with _stream(live) as response:
        events = EventReader(response)
        kind, snap = events.next()
        assert kind == "snapshot"
        assert any(n["id"] == "measure.umsatz" for n in snap["nodes"])
        assert live.hub.clients == 1

        path = live.workspace / "measures" / "umsatz.yaml"
        text = path.read_text(encoding="utf-8")
        start = time.monotonic()
        path.write_text(text.replace("name: Umsatz", "name: Nettoumsatz"), encoding="utf-8")
        kind, diff = events.next()
        latency = time.monotonic() - start

    print(f"\nLatenz Speichern → SSE-Diff: {latency * 1000:.0f} ms")
    assert kind == "diff"
    assert [n["name"] for n in diff["nodes"]["changed"]] == ["Nettoumsatz"]
    assert diff["version"] == snap["version"] + 1
    assert latency < LATENCY_BUDGET_S


def test_conflict_appears_and_node_removal(live: Live) -> None:
    with _stream(live) as response:
        events = EventReader(response)
        assert events.next()[0] == "snapshot"

        path = live.workspace / "measures" / "auftragsbestand.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "    statement: statement.0010\n",
                "    statement: statement.0010\n"
                "  - by: stakeholder.controlling-leitung\n"
                "    text: Bestätigte Aufträge abzüglich fakturierter Positionen\n"
                "    statement: statement.0011\n",
            ),
            encoding="utf-8",
        )
        kind, diff = events.next()
        assert kind == "diff"
        changed = {n["id"]: n for n in diff["nodes"]["changed"]}
        assert changed["measure.auftragsbestand"]["display"] == "conflict"
        assert [f["rule"] for f in diff["findings"]["added"]] == ["measure_definition_conflict"]

        (live.workspace / "questions" / "liefertermin-quelle.yaml").unlink()
        kind, diff = events.next()
        assert kind == "diff"
        assert diff["nodes"]["removed"] == ["question.liefertermin-quelle"]


def test_lotse_dir_and_non_yaml_are_ignored_and_caption_is_broadcast(live: Live) -> None:
    with _stream(live) as response:
        events = EventReader(response)
        assert events.next()[0] == "snapshot"
        (live.workspace / ".lotse" / "noise.yaml").write_text("x: 1\n")
        (live.workspace / "measures" / "notiz.txt").write_text("egal\n")
        time.sleep(0.6)
        httpx2.post(f"{live.url}/api/caption", json={"question": "F?", "answer": "A."})
        kind, data = events.next()
        # Erstes Ereignis nach dem Rauschen ist die Einblendung, kein Diff.
        assert (kind, data) == ("caption", {"question": "F?", "answer": "A."})
    assert live.hub.version == 1
