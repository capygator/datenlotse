"""In-Memory-Simulation der benötigten Azure-DevOps-REST-Endpunkte (kein Netzwerk)."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from lotse.gen.ado.rest import PARENT_LINK, HttpResponse

ORG = "https://dev.azure.com/testorg"
PROJECT = "Lotse Test"
PROJECT_PATH = "/testorg/Lotse%20Test/_apis/"
AGILE = {"Epic", "Feature", "User Story", "Task", "Bug", "Issue"}
SCRUM = {"Epic", "Feature", "Product Backlog Item", "Task", "Bug", "Impediment"}


@dataclass
class FakeItem:
    id: int
    type: str
    fields: dict[str, str]
    relations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def parent(self) -> int | None:
        for r in self.relations:
            if r["rel"] == PARENT_LINK:
                return int(r["url"].rsplit("/", 1)[-1])
        return None

    @property
    def tags(self) -> list[str]:
        return [t.strip() for t in self.fields.get("System.Tags", "").split(";") if t.strip()]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fields": {"System.WorkItemType": self.type, **self.fields},
            "relations": self.relations,
        }


class FakeAdo:
    """Aufrufbar wie ``HttpTransport``; protokolliert alle Requests."""

    def __init__(self, pat: str = "secret-pat", types: set[str] = AGILE) -> None:
        self.pat = pat
        self.types = types
        self.items: dict[int, FakeItem] = {}
        self.calls: list[tuple[str, str]] = []
        self._next = 100

    def add(self, type_name: str, fields: dict[str, str], parent: int | None = None) -> FakeItem:
        item = FakeItem(self._next, type_name, dict(fields))
        if parent is not None:
            item.relations.append(
                {"rel": PARENT_LINK, "url": f"{ORG}/_apis/wit/workItems/{parent}"}
            )
        self.items[item.id] = item
        self._next += 1
        return item

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] in ("POST", "PATCH") and "/wiql" not in c[1]]

    @staticmethod
    def _ok(data: Any, status: int = 200) -> HttpResponse:
        return HttpResponse(status, json.dumps(data).encode())

    @staticmethod
    def _err(status: int, message: str) -> HttpResponse:
        return HttpResponse(status, json.dumps({"message": message}).encode())

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> HttpResponse:
        self.calls.append((method, url))
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        assert query.get("api-version") == ["7.1"], url
        assert parts.path.startswith(PROJECT_PATH), url
        expected = "Basic " + base64.b64encode(f":{self.pat}".encode()).decode()
        if headers.get("Authorization") != expected:
            return HttpResponse(401, b"")
        path = parts.path[len(PROJECT_PATH) :]
        payload = json.loads(body) if body else None

        if method == "GET" and path == "wit/workitemtypes":
            return self._ok({"value": [{"name": t} for t in sorted(self.types)]})
        if method == "POST" and path == "wit/wiql":
            m = re.search(r"\[System\.Tags\] CONTAINS '([^']*)'", payload["query"])
            assert m, payload
            tag = m.group(1).lower()
            ids = [i for i, it in sorted(self.items.items()) if tag in map(str.lower, it.tags)]
            return self._ok({"workItems": [{"id": i} for i in ids]})
        if method == "GET" and path == "wit/workitems":
            assert query.get("$expand") == ["relations"]
            ids = [int(x) for x in query["ids"][0].split(",")]
            assert len(ids) <= 200
            return self._ok({"value": [self.items[i].to_json() for i in ids]})
        if method == "POST" and path.startswith("wit/workitems/$"):
            assert headers["Content-Type"] == "application/json-patch+json"
            type_name = unquote(path.removeprefix("wit/workitems/$"))
            if type_name not in self.types:
                return self._err(400, f"Work item type {type_name} does not exist")
            item = FakeItem(self._next, type_name, {})
            self._next += 1
            self._apply(item, payload)
            self.items[item.id] = item
            return self._ok(item.to_json())
        if method == "PATCH" and path.startswith("wit/workitems/"):
            assert headers["Content-Type"] == "application/json-patch+json"
            item = self.items[int(path.rsplit("/", 1)[-1])]
            self._apply(item, payload)
            return self._ok(item.to_json())
        return self._err(404, f"unbekannt: {method} {path}")

    def _apply(self, item: FakeItem, ops: list[dict[str, Any]]) -> None:
        for op in ops:
            assert op["op"] == "add", op
            if op["path"] == "/relations/-":
                rel = op["value"]
                assert rel["url"].startswith(f"{ORG}/_apis/wit/workItems/"), rel
                if rel["rel"] == PARENT_LINK:
                    assert item.parent is None, "zweiter Parent-Link"
                    assert int(rel["url"].rsplit("/", 1)[-1]) in self.items
                item.relations.append(rel)
            else:
                item.fields[op["path"].removeprefix("/fields/")] = op["value"]
