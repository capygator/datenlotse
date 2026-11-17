from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from conftest import Files, write_workspace

from lotse.query import stage_status
from lotse.serve.diff import apply_diff, diff_snapshots
from lotse.serve.state import Snapshot, display_status, make_snapshot


def _node(node_id: str, display: str = "draft", **extra: Any) -> dict[str, Any]:
    return {"id": node_id, "name": node_id, "display": display, "hash": "h", **extra}


def _snap(
    nodes: list[dict[str, Any]] | None = None,
    edges: list[tuple[str, str, str]] | None = None,
    findings: list[tuple[str, str, str]] | None = None,
    stages: list[dict[str, Any]] | None = None,
) -> Snapshot:
    snap = Snapshot(name="W")
    snap.nodes = {n["id"]: n for n in nodes or []}
    for src, kind, dst in edges or []:
        key = f"{src}|{kind}|{dst}"
        snap.edges[key] = {"id": key, "source": src, "target": dst, "kind": kind}
    snap.findings = [
        {"key": f"{r}|{n}|{m}", "rule": r, "severity": "gap", "node_id": n, "message": m}
        for r, n, m in findings or []
    ]
    snap.stages = stages or [{"stage": "measure", "progress": 0.0}]
    return snap


def test_identical_snapshots_give_no_diff() -> None:
    a = _snap([_node("measure.a")], [("measure.a", "grain", "dimension.k")], [("r", "x", "m")])
    assert diff_snapshots(a, copy.deepcopy(a)) is None


def test_nodes_added_removed_changed() -> None:
    old = _snap([_node("measure.a"), _node("measure.b")])
    new = _snap([_node("measure.a", display="conflict"), _node("measure.c")])
    d = diff_snapshots(old, new)
    assert d is not None
    assert [n["id"] for n in d["nodes"]["added"]] == ["measure.c"]
    assert d["nodes"]["removed"] == ["measure.b"]
    assert [n["id"] for n in d["nodes"]["changed"]] == ["measure.a"]
    assert d["nodes"]["changed"][0]["display"] == "conflict"


def test_content_hash_change_counts_as_change() -> None:
    old = _snap([_node("measure.a")])
    new = _snap([{**_node("measure.a"), "hash": "other"}])
    d = diff_snapshots(old, new)
    assert d is not None and [n["id"] for n in d["nodes"]["changed"]] == ["measure.a"]


def test_edges_and_findings() -> None:
    old = _snap(edges=[("a", "k", "b")], findings=[("r1", "a", "x")])
    new = _snap(edges=[("a", "k", "c")], findings=[("r2", "a", "y")])
    d = diff_snapshots(old, new)
    assert d is not None
    assert [e["id"] for e in d["edges"]["added"]] == ["a|k|c"]
    assert d["edges"]["removed"] == ["a|k|b"]
    assert [f["key"] for f in d["findings"]["added"]] == ["r2|a|y"]
    assert d["findings"]["removed"] == ["r1|a|x"]


def test_stage_change_alone_is_a_diff() -> None:
    old = _snap(stages=[{"stage": "measure", "progress": 0.0}])
    new = _snap(stages=[{"stage": "measure", "progress": 0.5}])
    d = diff_snapshots(old, new)
    assert d is not None and d["stages"] == new.stages


def test_display_status_precedence() -> None:
    assert display_status("measure", "agreed", []) == "agreed"
    assert display_status("measure", "agreed", ["warn", "info"]) == "agreed"
    assert display_status("measure", "agreed", ["gap"]) == "gap"
    assert display_status("measure", "draft", ["gap", "conflict"]) == "conflict"
    assert display_status("measure", "conflict", ["error", "conflict"]) == "error"
    assert display_status("measure", "conflict", []) == "conflict"
    assert display_status("question", "open", []) == "gap"
    assert display_status("question", "answered", []) == "agreed"
    assert display_status("statement", None, []) == "neutral"


def _snapshot_of(root: Path, files: Files) -> Snapshot:
    from lotse.store.build import build

    result = build(write_workspace(root, files))
    return make_snapshot(result, stage_status(result.db_path))


def test_real_build_conflict_diff_roundtrip(tmp_path: Path, base: Files) -> None:
    old = _snapshot_of(tmp_path / "a", base)
    assert old.nodes["measure.m"]["display"] == "draft"

    changed = copy.deepcopy(base)
    changed["stakeholders/zwei.yaml"] = {"id": "stakeholder.zwei", "name": "Zwei"}
    changed["measures/m.yaml"]["definitions"].append({"by": "stakeholder.zwei", "text": "Y"})
    new = _snapshot_of(tmp_path / "b", changed)

    d = diff_snapshots(old, new)
    assert d is not None
    assert [n["id"] for n in d["nodes"]["added"]] == ["stakeholder.zwei"]
    changed_ids = {n["id"]: n for n in d["nodes"]["changed"]}
    assert changed_ids["measure.m"]["display"] == "conflict"
    assert any(f["rule"] == "measure_definition_conflict" for f in d["findings"]["added"])
    assert "measure.m|definition_by|stakeholder.zwei" in [e["id"] for e in d["edges"]["added"]]

    applied = apply_diff(old.to_dict(), d)
    expected = new.to_dict()

    def norm(s: dict[str, Any]) -> dict[str, Any]:
        return {
            "nodes": sorted(s["nodes"], key=lambda n: n["id"]),
            "edges": sorted(s["edges"], key=lambda e: e["id"]),
            "findings": sorted(s["findings"], key=lambda f: f["key"]),
            "stages": s["stages"],
        }

    # Dateipfade unterscheiden sich nicht (relativ), daher exakter Vergleich möglich.
    assert norm(applied) == norm(expected)
