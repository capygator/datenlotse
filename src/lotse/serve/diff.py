"""Differenz zweier Momentaufnahmen: reine Logik ohne Ein-/Ausgabe."""

from __future__ import annotations

from typing import Any

from lotse.serve.state import Snapshot


def _keyed(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["key"]: item for item in items}


def diff_snapshots(old: Snapshot, new: Snapshot) -> dict[str, Any] | None:
    """Was sich von ``old`` zu ``new`` geändert hat, oder ``None`` ohne Änderung.

    Knoten gelten als geändert, wenn sich irgendein Feld unterscheidet (auch Inhalts-Hash
    und Darstellungsstatus). Kanten und Befunde werden über ihren Schlüssel verglichen.
    Stufen und Workspace-Name werden bei jeder Änderung vollständig mitgeschickt.
    """
    added = [n for k, n in new.nodes.items() if k not in old.nodes]
    removed = [k for k in old.nodes if k not in new.nodes]
    changed = [n for k, n in new.nodes.items() if k in old.nodes and old.nodes[k] != n]

    edges_added = [e for k, e in new.edges.items() if k not in old.edges]
    edges_removed = [k for k in old.edges if k not in new.edges]

    old_f, new_f = _keyed(old.findings), _keyed(new.findings)
    findings_added = [f for k, f in new_f.items() if k not in old_f or old_f[k] != f]
    findings_removed = [k for k in old_f if k not in new_f]

    if not (
        added
        or removed
        or changed
        or edges_added
        or edges_removed
        or findings_added
        or findings_removed
        or old.stages != new.stages
        or old.name != new.name
    ):
        return None
    return {
        "name": new.name,
        "nodes": {"added": added, "removed": removed, "changed": changed},
        "edges": {"added": edges_added, "removed": edges_removed},
        "findings": {"added": findings_added, "removed": findings_removed},
        "stages": new.stages,
    }


def apply_diff(snapshot: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    """Wendet ``diff`` auf eine ``Snapshot.to_dict()``-Form an (Referenz für den Viewer)."""
    nodes = {n["id"]: n for n in snapshot["nodes"]}
    for key in diff["nodes"]["removed"]:
        nodes.pop(key, None)
    for n in diff["nodes"]["added"] + diff["nodes"]["changed"]:
        nodes[n["id"]] = n
    edges = {e["id"]: e for e in snapshot["edges"]}
    for key in diff["edges"]["removed"]:
        edges.pop(key, None)
    for e in diff["edges"]["added"]:
        edges[e["id"]] = e
    findings = _keyed(snapshot["findings"])
    for key in diff["findings"]["removed"]:
        findings.pop(key, None)
    for f in diff["findings"]["added"]:
        findings[f["key"]] = f
    return {
        "name": diff["name"],
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(edges.values(), key=lambda e: e["id"]),
        "findings": list(findings.values()),
        "stages": diff["stages"],
    }
