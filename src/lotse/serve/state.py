"""Momentaufnahme eines Builds für den Live-Viewer (reine Daten, JSON-fähig)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from lotse.model.entities import Measure, Question
from lotse.model.finding import Finding
from lotse.model.registry import BY_NAME, SEVERITIES, STAGES
from lotse.query import StageStatus
from lotse.store.build import BuildResult
from lotse.store.loader import LoadedEntity

DISPLAY_STATES: tuple[str, ...] = ("error", "conflict", "gap", "draft", "agreed", "neutral")
"""Darstellungsstatus, wichtigster zuerst."""

_SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}
_STAGE_ORD = {t.name: t.stage for t in STAGES}
_OVERRIDES = ("error", "conflict", "gap")
"""Befund-Severities, die den YAML-Status in der Darstellung überstimmen."""


def finding_key(f: Finding) -> str:
    return f"{f.rule}|{f.node_id or ''}|{f.message}"


def display_status(node_type: str, yaml_status: str | None, severities: list[str]) -> str:
    """Status für Farbe und Symbol: höchste Befund-Severity schlägt den YAML-Status.

    ``error``, ``conflict`` und ``gap`` überstimmen; ``warn`` und ``info`` nicht.
    """
    for sev in _OVERRIDES:
        if sev in severities:
            return sev
    if node_type == "question":
        return "gap" if yaml_status == "open" else "agreed"
    if yaml_status in ("agreed", "conflict", "draft"):
        return yaml_status
    return "neutral" if BY_NAME[node_type].stage is None else "draft"


def _content_hash(entity: LoadedEntity) -> str:
    raw = json.dumps(entity.model.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _stage_dict(s: StageStatus) -> dict[str, Any]:
    return {
        "stage": s.stage,
        "label": s.label,
        "state": s.state,
        "nodes": s.nodes,
        "clean": s.clean,
        "progress": round(s.progress, 4),
        "findings": dict(sorted(s.findings.items())),
    }


@dataclass
class Snapshot:
    """Vollständiger Stand: Knoten, Kanten, Befunde, Stufen. Schlüssel sind stabil."""

    name: str
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[str, dict[str, Any]] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    stages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
            "findings": self.findings,
            "stages": self.stages,
        }


def make_snapshot(result: BuildResult, stages: list[StageStatus]) -> Snapshot:
    cfg = result.loaded.config
    snap = Snapshot(name=cfg.name if cfg else result.workspace.name)
    by_node: dict[str, list[str]] = {}
    for f in result.findings:
        if f.node_id:
            by_node.setdefault(f.node_id, []).append(f.severity)
    hashes = {e.id: _content_hash(e) for e in result.loaded.entities}

    for node_id, ntype, name, status, stage, file in result.graph.nodes:
        sevs = sorted(by_node.get(node_id, []), key=lambda s: _SEVERITY_RANK[s])
        etype = BY_NAME[ntype]
        snap.nodes[node_id] = {
            "id": node_id,
            "type": ntype,
            "type_label": etype.label,
            "name": name,
            "status": status,
            "stage": stage,
            "stage_ord": etype.stage,
            "file": file,
            "display": display_status(ntype, status, sevs),
            "findings": dict(sorted(Counter(sevs).items(), key=lambda kv: _SEVERITY_RANK[kv[0]])),
            "hash": hashes.get(node_id, ""),
        }
    for src, dst, kind in result.graph.edges:
        key = f"{src}|{kind}|{dst}"
        snap.edges[key] = {"id": key, "source": src, "target": dst, "kind": kind}

    seen: Counter[str] = Counter()
    for f in result.findings:
        base = finding_key(f)
        seen[base] += 1
        key = base if seen[base] == 1 else f"{base}#{seen[base]}"
        node = snap.nodes.get(f.node_id) if f.node_id else None
        snap.findings.append(
            {
                "key": key,
                "rule": f.rule,
                "severity": f.severity,
                "node_id": f.node_id,
                "node_name": node["name"] if node else None,
                "stage_ord": _STAGE_ORD.get(node["type"]) if node else None,
                "message": f.message,
            }
        )
    snap.stages = [_stage_dict(s) for s in stages]
    return snap


def node_detail(result: BuildResult, node_id: str) -> dict[str, Any] | None:
    """Definitionen, Herkunft (Aussagen), offene Fragen, Befunde und Nachbarn eines Knotens."""
    entities = {e.id: e for e in result.loaded.entities}
    entity = entities.get(node_id)
    if entity is None:
        return None

    def name_of(ref: str | None) -> str | None:
        if ref is None:
            return None
        other = entities.get(ref)
        if other is None:
            return None
        data = other.model.model_dump()
        return str(data.get("name") or data.get("text") or ref)

    def statement(ref: str | None) -> dict[str, Any] | None:
        if ref is None:
            return None
        other = entities.get(ref)
        if other is None:
            return {"id": ref, "text": None, "by": None, "by_name": None}
        data = other.model.model_dump()
        by = data.get("by")
        return {"id": ref, "text": data.get("text"), "by": by, "by_name": name_of(by)}

    model = entity.model
    attrs = model.model_dump(mode="json", exclude_none=True)

    definitions: list[dict[str, Any]] = []
    if isinstance(model, Measure):
        definitions = [
            {
                "by": d.by,
                "by_name": name_of(d.by),
                "text": d.text,
                "statement": statement(d.statement),
            }
            for d in model.definitions
        ]

    provenance: list[dict[str, Any]] = []
    refs = [attrs.get("statement")] + [d["statement"]["id"] for d in definitions if d["statement"]]
    for ref in refs:
        st = statement(ref)
        if st and st not in provenance:
            provenance.append(st)

    questions = [
        {
            "id": e.id,
            "text": e.model.text,
            "owner": e.model.owner,
            "owner_name": name_of(e.model.owner),
        }
        for e in result.loaded.entities
        if isinstance(e.model, Question)
        and e.model.status == "open"
        and (node_id in e.model.about or e.id == node_id)
    ]

    neighbors = [
        {"kind": kind, "id": dst, "name": name_of(dst), "direction": "out"}
        for src, dst, kind in result.graph.edges
        if src == node_id
    ] + [
        {"kind": kind, "id": src, "name": name_of(src), "direction": "in"}
        for src, dst, kind in result.graph.edges
        if dst == node_id
    ]

    findings = [
        {"rule": f.rule, "severity": f.severity, "message": f.message}
        for f in result.findings
        if f.node_id == node_id
    ]
    return {
        "id": node_id,
        "type": entity.type.name,
        "type_label": entity.type.label,
        "name": name_of(node_id),
        "file": entity.file,
        "attributes": attrs,
        "definitions": definitions,
        "provenance": provenance,
        "questions": questions,
        "findings": findings,
        "neighbors": neighbors,
    }
