"""FastAPI-App für ``lotse serve``: Dateiwächter → Neubau → Diff → Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel
from watchfiles import Change, awatch

from lotse.query import stage_status
from lotse.serve.diff import diff_snapshots
from lotse.serve.state import Snapshot, make_snapshot, node_detail
from lotse.store.build import BuildResult, build
from lotse.store.workspace import INDEX_DIR

log = logging.getLogger("lotse.serve")

SERVE_DB = "serve.duckdb"
"""Eigene Index-Datei, damit parallele ``lotse next``/``status``-Läufe nicht kollidieren."""

KEEPALIVE_S = 15.0
WATCH_DEBOUNCE_MS = 300
WATCH_STEP_MS = 30


@dataclass(frozen=True)
class Event:
    kind: str
    data: dict[str, Any]

    def encode(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
        return f"event: {self.kind}\ndata: {payload}\n\n"


class Caption(BaseModel):
    question: str | None = None
    answer: str | None = None
    text: str | None = None


def yaml_filter(workspace: Path) -> Any:
    """Nur ``*.yaml`` im Workspace, nichts unter ``.lotse/``."""
    root = workspace.resolve()

    def accept(_change: Change, path: str) -> bool:
        p = Path(path)
        if p.suffix != ".yaml":
            return False
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            rel = p
        return INDEX_DIR not in rel.parts

    return accept


class Hub:
    """Hält den letzten Stand und verteilt Ereignisse an alle verbundenen Clients."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.db_path = self.workspace / INDEX_DIR / SERVE_DB
        self.result: BuildResult | None = None
        self.snapshot: Snapshot | None = None
        self.version = 0
        self.caption: dict[str, Any] | None = None
        self.watching = asyncio.Event()
        self._clients: set[asyncio.Queue[Event | None]] = set()
        self._lock = asyncio.Lock()

    def _build(self) -> tuple[BuildResult, Snapshot]:
        result = build(self.workspace, self.db_path)
        return result, make_snapshot(result, stage_status(result.db_path))

    async def rebuild(self) -> dict[str, Any] | None:
        """Neubau im Thread; sendet den Diff, falls sich etwas geändert hat."""
        async with self._lock:
            result, snap = await asyncio.to_thread(self._build)
            old = self.snapshot
            self.result, self.snapshot = result, snap
            if old is None:
                self.version += 1
                return None
            diff = diff_snapshots(old, snap)
            if diff is None:
                return None
            self.version += 1
            diff["version"] = self.version
            self.publish(Event("diff", diff))
            return diff

    def state(self) -> dict[str, Any]:
        if self.snapshot is None:
            raise HTTPException(503, "Noch kein Build vorhanden.")
        return {**self.snapshot.to_dict(), "version": self.version, "caption": self.caption}

    def set_caption(self, caption: dict[str, Any] | None) -> None:
        self.caption = caption
        self.publish(Event("caption", caption or {}))

    def publish(self, event: Event) -> None:
        for queue in self._clients:
            queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue[Event | None]:
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event | None]) -> None:
        self._clients.discard(queue)

    def close(self) -> None:
        for queue in self._clients:
            queue.put_nowait(None)

    @property
    def clients(self) -> int:
        return len(self._clients)

    async def watch(self, stop: asyncio.Event) -> None:
        """Wartet auf YAML-Änderungen und baut neu, bis ``stop`` gesetzt ist."""
        changes = awatch(
            self.workspace,
            watch_filter=yaml_filter(self.workspace),
            debounce=WATCH_DEBOUNCE_MS,
            step=WATCH_STEP_MS,
            stop_event=stop,
        )
        # Der erste __anext__ legt den Wächter an; danach gilt er als bereit.
        first = asyncio.ensure_future(anext(changes))
        await asyncio.sleep(0.2)
        self.watching.set()
        pending: Any = first
        while True:
            try:
                batch = await pending
            except StopAsyncIteration:
                return
            log.info("Änderung: %s", sorted(p for _, p in batch))
            try:
                await self.rebuild()
            except Exception:  # Neubau darf den Wächter nicht beenden
                log.exception("Neubau fehlgeschlagen")
            pending = anext(changes)


VENDOR_FILES = frozenset({"cytoscape.min.js", "elk.bundled.js", "cytoscape-elk.js"})
"""Im Paket mitgelieferte Viewer-Bibliotheken (offline-fähig, Lizenzen in viewer/vendor/)."""


def viewer_html() -> str:
    return resources.files("lotse.viewer").joinpath("index.html").read_text(encoding="utf-8")


async def _event_stream(hub: Hub, request: Request) -> AsyncIterator[str]:
    queue = hub.subscribe()  # vor dem Snapshot registrieren, damit kein Diff verloren geht
    try:
        yield "retry: 1000\n\n"
        yield Event("snapshot", hub.state()).encode()
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield ": keepalive\n\n"
                continue
            if event is None:
                return
            yield event.encode()
    finally:
        hub.unsubscribe(queue)


def create_app(workspace: Path, *, watch: bool = True) -> FastAPI:
    hub = Hub(workspace)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await hub.rebuild()
        stop = asyncio.Event()
        task = asyncio.create_task(hub.watch(stop)) if watch else None
        try:
            yield
        finally:
            stop.set()
            hub.close()
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="lotse", lifespan=lifespan)
    app.state.hub = hub

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(viewer_html())

    @app.get("/vendor/{name}")
    async def vendor(name: str) -> Response:
        if name not in VENDOR_FILES:
            raise HTTPException(status_code=404)
        data = resources.files("lotse.viewer").joinpath("vendor", name).read_bytes()
        return Response(
            data,
            media_type="text/javascript",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/graph")
    async def graph() -> dict[str, Any]:
        return hub.state()

    @app.get("/api/node/{node_id}")
    async def node(node_id: str) -> dict[str, Any]:
        if hub.result is None:
            raise HTTPException(503, "Noch kein Build vorhanden.")
        detail = node_detail(hub.result, node_id)
        if detail is None:
            raise HTTPException(404, f"Knoten {node_id} nicht gefunden.")
        return detail

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        return StreamingResponse(
            _event_stream(hub, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/caption")
    async def caption(body: Caption) -> dict[str, Any]:
        """Einblendung setzen (z. B. Frage und Antwort im Replay); leerer Body löscht sie."""
        data = body.model_dump(exclude_none=True)
        hub.set_caption(data or None)
        return {"caption": hub.caption}

    return app
