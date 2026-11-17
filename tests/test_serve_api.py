from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import NORDWIND
from fastapi.testclient import TestClient

from lotse.serve import create_app
from lotse.serve.app import SERVE_DB, viewer_html, yaml_filter
from lotse.store.workspace import index_path


@pytest.fixture
def nordwind(tmp_path: Path) -> Path:
    target = tmp_path / "nordwind"
    shutil.copytree(NORDWIND, target, ignore=shutil.ignore_patterns(".lotse"))
    return target


@pytest.fixture
def client(nordwind: Path) -> Iterator[TestClient]:
    with TestClient(create_app(nordwind, watch=False)) as c:
        yield c


def test_viewer_is_packaged_and_served(client: TestClient) -> None:
    html = viewer_html()
    assert "cytoscape" in html and "cytoscape-elk" in html and "elk.bundled.js" in html
    assert 'lang="de"' in html
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Befunde" in r.text and "/api/events" in r.text


def test_graph_contains_nodes_findings_and_stages(client: TestClient, nordwind: Path) -> None:
    data = client.get("/api/graph").json()
    assert data["name"]
    nodes = {n["id"]: n for n in data["nodes"]}
    assert len(nodes) == 42
    assert nodes["measure.auftragsbestand"]["display"] == "agreed"
    assert nodes["table.fact_lieferzusage"]["display"] == "gap"
    assert nodes["statement.0001"]["display"] == "neutral"
    assert [(f["rule"], f["node_id"]) for f in data["findings"]] == [
        ("table_without_source", "table.fact_lieferzusage")
    ]
    assert [s["stage"] for s in data["stages"]] == [
        "decision",
        "product",
        "measure",
        "dimension",
        "table",
        "source",
    ]
    table = next(s for s in data["stages"] if s["stage"] == "table")
    assert table["clean"] == table["nodes"] - 1
    assert data["caption"] is None
    # Serve nutzt eine eigene Index-Datei, damit parallele CLI-Läufe nicht kollidieren.
    assert (nordwind / ".lotse" / SERVE_DB).is_file()
    assert not index_path(nordwind).exists()


def test_node_detail_has_definitions_provenance_questions(client: TestClient) -> None:
    d = client.get("/api/node/measure.auftragsbestand").json()
    assert d["type_label"] == "Kennzahl"
    assert len(d["definitions"]) == 1
    assert d["definitions"][0]["statement"]["text"].startswith("Auftragsbestand ist")
    assert {p["id"] for p in d["provenance"]} == {"statement.0012", "statement.0010"}
    assert all(p["by_name"] for p in d["provenance"])

    q = client.get("/api/node/table.fact_lieferzusage").json()
    assert [x["id"] for x in q["questions"]] == ["question.liefertermin-quelle"]
    assert q["findings"][0]["severity"] == "gap"
    assert client.get("/api/node/measure.gibtsnicht").status_code == 404


def test_caption_roundtrip(client: TestClient) -> None:
    body = {"question": "Wer verantwortet Umsatz?", "answer": "Das Controlling."}
    r = client.post("/api/caption", json=body)
    assert r.json()["caption"] == body
    assert client.get("/api/graph").json()["caption"] == body
    client.post("/api/caption", json={})
    assert client.get("/api/graph").json()["caption"] is None


def test_yaml_filter(tmp_path: Path) -> None:
    accept = yaml_filter(tmp_path)
    from watchfiles import Change

    assert accept(Change.modified, str(tmp_path / "measures" / "a.yaml"))
    assert accept(Change.deleted, str(tmp_path / "measures" / "a.yaml"))
    assert not accept(Change.modified, str(tmp_path / "measures" / "a.yaml.swp"))
    assert not accept(Change.modified, str(tmp_path / ".lotse" / "serve.duckdb"))
    assert not accept(Change.added, str(tmp_path / ".lotse" / "x.yaml"))
