"""REST-Umsetzung von :class:`WorkItemStore` gegen die Azure DevOps Work Items API 7.1.

Alle API-Details (URLs, JSON-Patch, Link-Typ, Auth) stehen hier und nur hier. Der HTTP-Zugriff
liegt hinter :class:`HttpTransport`; Standard ist ``urllib`` aus der Standardbibliothek, Tests
setzen einen Fake ein.

Verwendete Endpunkte (``{p}`` = ``https://dev.azure.com/{org}/{project}``):

- ``GET  {p}/_apis/wit/workitemtypes``               Typen prüfen (Agile/Scrum)
- ``POST {p}/_apis/wit/wiql``                        Items mit Scope-Tag finden
- ``GET  {p}/_apis/wit/workitems?ids=…&$expand=relations``  Felder, Tags, Parent laden
- ``POST {p}/_apis/wit/workitems/${type}``           anlegen (JSON-Patch, inkl. Parent-Link)
- ``PATCH {p}/_apis/wit/workitems/{id}``             Felder ändern / Parent-Link ergänzen
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from lotse.gen.ado.sync import (
    F_ACCEPTANCE,
    F_DESCRIPTION,
    F_TAGS,
    F_TITLE,
    AdoError,
    RemoteItem,
    split_tags,
)

API_VERSION = "7.1"
PARENT_LINK = "System.LinkTypes.Hierarchy-Reverse"
BATCH_SIZE = 200
JSON = "application/json"
JSON_PATCH = "application/json-patch+json"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    content_type: str = JSON


HttpTransport = Callable[[str, str, dict[str, str], bytes | None], HttpResponse]
"""``(method, url, headers, body) -> HttpResponse``; HTTP-Fehlerstatus wird zurückgegeben,
nicht geworfen."""


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return HttpResponse(
                response.status, response.read(), response.headers.get("Content-Type", "")
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, exc.read(), exc.headers.get("Content-Type", ""))
    except urllib.error.URLError as exc:
        raise AdoError(f"Azure DevOps nicht erreichbar: {exc.reason}") from exc


def org_url(org: str) -> str:
    """``myorg`` oder ``https://dev.azure.com/myorg`` → Basis-URL ohne Schrägstrich am Ende."""
    org = org.strip().rstrip("/")
    if org.startswith(("https://", "http://")):
        return org
    return f"https://dev.azure.com/{quote(org, safe='')}"


def _parent_id(relations: list[dict[str, Any]] | None) -> int | None:
    for rel in relations or []:
        if rel.get("rel") == PARENT_LINK:
            tail = str(rel.get("url", "")).rstrip("/").rsplit("/", 1)[-1]
            if tail.isdigit():
                return int(tail)
    return None


def _remote(data: dict[str, Any]) -> RemoteItem:
    raw = data.get("fields", {})
    fields = {k: str(raw[k]) for k in (F_TITLE, F_DESCRIPTION, F_ACCEPTANCE, F_TAGS) if k in raw}
    return RemoteItem(
        id=int(data["id"]),
        type=str(raw.get("System.WorkItemType", "")),
        fields=fields,
        tags=split_tags(raw.get(F_TAGS)),
        parent_id=_parent_id(data.get("relations")),
    )


class RestWorkItemStore:
    def __init__(
        self, org: str, project: str, pat: str, transport: HttpTransport | None = None
    ) -> None:
        if not pat:
            raise AdoError("Kein PAT angegeben.")
        self.org = org_url(org)
        self.project_url = f"{self.org}/{quote(project, safe='')}"
        token = base64.b64encode(f":{pat}".encode()).decode("ascii")
        self._auth = f"Basic {token}"
        self._transport = transport or urllib_transport

    # --- HTTP ----------------------------------------------------------------------------

    def _call(
        self, method: str, path: str, payload: Any = None, content_type: str = JSON
    ) -> dict[str, Any]:
        sep = "&" if "?" in path else "?"
        url = f"{self.project_url}/_apis/{path}{sep}api-version={API_VERSION}"
        headers = {"Authorization": self._auth, "Accept": JSON}
        body = None
        if payload is not None:
            headers["Content-Type"] = content_type
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response = self._transport(method, url, headers, body)
        where = f"{method} {url.split('?', 1)[0]}"
        if response.status in (401, 403):
            raise AdoError(
                f"{where}: HTTP {response.status}, Zugriff verweigert. PAT gültig und mit "
                "Scope „Work Items (Read & write)“ für diese Organisation?"
            )
        try:
            data = json.loads(response.body.decode("utf-8")) if response.body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
        if response.status == 203 or not isinstance(data, dict):
            raise AdoError(
                f"{where}: unerwartete Antwort (HTTP {response.status}, keine JSON-Daten). "
                "Meist ein ungültiger PAT oder eine falsche Organisation."
            )
        if response.status >= 400:
            message = data.get("message") or "ohne Meldung"
            raise AdoError(f"{where}: HTTP {response.status}: {message}")
        return data

    # --- WorkItemStore -------------------------------------------------------------------

    def work_item_types(self) -> set[str]:
        data = self._call("GET", "wit/workitemtypes")
        return {str(t["name"]) for t in data.get("value", [])}

    def find_managed(self, scope_tag: str) -> list[RemoteItem]:
        tag = scope_tag.replace("'", "''")
        query = (
            "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
            f"AND [System.Tags] CONTAINS '{tag}' ORDER BY [System.Id]"
        )
        data = self._call("POST", "wit/wiql", {"query": query})
        ids = [int(w["id"]) for w in data.get("workItems", [])]
        items: list[RemoteItem] = []
        for start in range(0, len(ids), BATCH_SIZE):
            chunk = ",".join(str(i) for i in ids[start : start + BATCH_SIZE])
            batch = self._call("GET", f"wit/workitems?ids={chunk}&$expand=relations")
            items += [_remote(v) for v in batch.get("value", [])]
        return sorted(items, key=lambda i: i.id)

    def _link(self, parent_id: int) -> dict[str, Any]:
        return {
            "op": "add",
            "path": "/relations/-",
            "value": {"rel": PARENT_LINK, "url": f"{self.org}/_apis/wit/workItems/{parent_id}"},
        }

    def create(self, type_name: str, fields: dict[str, str], parent_id: int | None) -> RemoteItem:
        ops: list[dict[str, Any]] = [
            {"op": "add", "path": f"/fields/{k}", "value": v} for k, v in fields.items()
        ]
        if parent_id is not None:
            ops.append(self._link(parent_id))
        data = self._call("POST", f"wit/workitems/${quote(type_name)}", ops, JSON_PATCH)
        return _remote(data)

    def update(self, item_id: int, fields: dict[str, str]) -> None:
        ops = [{"op": "add", "path": f"/fields/{k}", "value": v} for k, v in fields.items()]
        self._call("PATCH", f"wit/workitems/{item_id}", ops, JSON_PATCH)

    def set_parent(self, item_id: int, parent_id: int) -> None:
        self._call("PATCH", f"wit/workitems/{item_id}", [self._link(parent_id)], JSON_PATCH)
