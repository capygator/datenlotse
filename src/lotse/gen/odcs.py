"""ODCS-v3.1.0-Generator: ein Data Contract (YAML) je Datenprodukt.

Validierung gegen das offizielle JSON-Schema (bitol-io/open-data-contract-standard, Tag
v3.1.0), vendored als ``lotse/gen/schemas/odcs-json-schema-v3.1.0.json`` (Quelle, Commit
und SHA-256 in ``lotse/gen/schemas/README.md``).

Abbildung:

- Produkt → Contract (``id`` = Slug, ``status``: agreed → proposed, sonst draft)
- Tabellen (aus Kennzahlen, Grain-Dimensionen und Referenzen) → ``schema[]``,
  Spalten → ``properties[]``, ``references`` → Fremdschlüssel-``relationships``
- Kennzahlen mit allen Definitionen, Owner, Einheit, Grain, Zeitlogik → ``customProperties``
  (ODCS 3.1.0 kennt kein Kennzahl-Objekt); Qualitätsregeln der Kennzahlen → ``quality``
  (``type: text``) an der ersten Tabelle der Kennzahl
- Owner und Definitionsgeber → ``team.members``; offene Befunde → ``description.limitations``
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

import yaml
from jsonschema import Draft201909Validator

from lotse.gen.common import Index, ident, key_column, product_scope, slug
from lotse.model.entities import (
    Column,
    Decision,
    Dimension,
    Measure,
    Product,
    Source,
    Stakeholder,
    Table,
)
from lotse.store.build import BuildResult

API_VERSION = "v3.1.0"
CONTRACT_VERSION = "0.1.0"
SCHEMA_FILE = "odcs-json-schema-v3.1.0.json"
FOLDER = "odcs"

LOGICAL_TYPE = {
    "string": "string",
    "int64": "integer",
    "decimal": "number",
    "double": "number",
    "date": "date",
    "datetime": "timestamp",
    "boolean": "boolean",
}
CONTRACT_STATUS = {"agreed": "proposed", "draft": "draft", "conflict": "draft"}


class OdcsError(Exception):
    pass


@cache
def _validator() -> Draft201909Validator:
    text = resources.files("lotse.gen.schemas").joinpath(SCHEMA_FILE).read_text(encoding="utf-8")
    return Draft201909Validator(json.loads(text))


def validate(contract: dict[str, Any]) -> list[str]:
    """Schemafehler als Texte (leer = gültig)."""
    return sorted(
        f"{'/'.join(str(p) for p in err.absolute_path) or '(root)'}: {err.message}"
        for err in _validator().iter_errors(contract)
    )


def _property(table: Table, col: Column, index: Index, in_scope: set[str]) -> dict[str, Any]:
    prop: dict[str, Any] = {"id": ident(col.name), "name": col.name}
    if col.description:
        prop["description"] = col.description
    prop["logicalType"] = LOGICAL_TYPE[col.type]
    prop["physicalType"] = col.type
    if col.key:
        keys = [c.name for c in table.columns if c.key]
        prop["primaryKey"] = True
        prop["primaryKeyPosition"] = keys.index(col.name) + 1
        prop["required"] = True
    if col.references and col.references in in_scope:
        target = index.get(col.references, Table)
        target_col = key_column(target) if target else None
        ref = f"{ident(slug(col.references))}.{target_col}" if target_col else None
        if ref and ident(target_col or "") == target_col:
            prop["relationships"] = [{"type": "foreignKey", "to": ref}]
    return prop


def _quality(measures: list[Measure], table_id: str) -> list[dict[str, Any]]:
    checks = []
    for m in measures:
        if not m.from_tables or m.from_tables[0] != table_id:
            continue
        for q in m.quality:
            description = f"Kennzahl {m.name}: Regel {q.rule}"
            if q.description:
                description += f" ({q.description})"
            checks.append(
                {
                    "id": f"{slug(m.id)}-{ident(q.rule)}",
                    "name": q.rule,
                    "type": "text",
                    "description": description,
                    "customProperties": [{"property": "measure", "value": m.id}],
                }
            )
    return checks


def _schema_object(
    table: Table, measures: list[Measure], index: Index, in_scope: set[str]
) -> dict[str, Any]:
    name = ident(slug(table.id))
    obj: dict[str, Any] = {
        "id": name,
        "name": name,
        "physicalName": name,
        "physicalType": "table",
        "businessName": table.name,
    }
    if table.description:
        obj["description"] = table.description
    obj["logicalType"] = "object"
    keys = [c.name for c in table.columns if c.key]
    if keys:
        obj["dataGranularityDescription"] = f"Eine Zeile je {', '.join(keys)}"
    obj["tags"] = [table.kind]
    obj["properties"] = [_property(table, c, index, in_scope) for c in table.columns]
    quality = _quality(measures, table.id)
    if quality:
        obj["quality"] = quality
    sources = [s for sid in table.from_sources if (s := index.get(sid, Source)) is not None]
    custom: list[dict[str, Any]] = [
        {"property": "lotseId", "value": table.id},
        {"property": "status", "value": table.status},
    ]
    if sources:
        custom.append(
            {
                "property": "sources",
                "value": [{"id": s.id, "name": s.name, "system": s.system} for s in sources],
            }
        )
    obj["customProperties"] = custom
    return obj


def _stakeholder_name(index: Index, sid: str | None) -> str | None:
    if sid is None:
        return None
    s = index.get(sid, Stakeholder)
    return s.name if s else sid


def _measure(m: Measure, index: Index) -> dict[str, Any]:
    out: dict[str, Any] = {"id": m.id, "name": m.name, "status": m.status}
    if m.description:
        out["description"] = m.description
    if m.owner:
        out["owner"] = _stakeholder_name(index, m.owner)
    if m.unit:
        out["unit"] = m.unit
    out["definitions"] = [
        {"by": _stakeholder_name(index, d.by), "text": d.text}
        | ({"statement": d.statement} if d.statement else {})
        for d in m.definitions
    ]
    if m.time_logic:
        out["timeLogic"] = m.time_logic
    grain = [(dim.name if (dim := index.get(g, Dimension)) else g) for g in m.grain]
    if grain:
        out["grain"] = grain
    out["fromTables"] = [ident(slug(t)) for t in m.from_tables]
    if m.quality:
        out["quality"] = [q.rule for q in m.quality]
    return out


def _team(product: Product, measures: list[Measure], index: Index) -> dict[str, Any]:
    roles: dict[str, list[str]] = {}

    def add(sid: str | None, role: str) -> None:
        if sid and role not in roles.setdefault(sid, []):
            roles[sid].append(role)

    add(product.owner, "Produkt-Owner")
    for m in measures:
        add(m.owner, f"Owner {m.name}")
    for m in measures:
        for d in m.definitions:
            add(d.by, f"Definition {m.name}")
    members = []
    for sid, rs in roles.items():
        member: dict[str, Any] = {"username": slug(sid)}
        s = index.get(sid, Stakeholder)
        if s:
            member["name"] = s.name
            if s.role:
                member["description"] = s.role
        member["role"] = ", ".join(rs)
        members.append(member)
    return {"name": index.workspace_name, "members": members}


def build_contract(result: BuildResult, product: Product) -> dict[str, Any]:
    index = Index(result)
    measures, tables = product_scope(index, product)
    in_scope = {t.id for t in tables}

    decisions = [d for did in product.serves if (d := index.get(did, Decision)) is not None]
    description: dict[str, Any] = {}
    purpose = product.description or "; ".join(
        d.name + (f": {d.description}" if d.description else "") for d in decisions
    )
    if purpose:
        description["purpose"] = purpose
    if decisions:
        description["usage"] = "Stützt die Entscheidung(en): " + ", ".join(
            d.name for d in decisions
        )
    relevant = {product.id} | {m.id for m in measures} | in_scope
    for m in measures:
        relevant.update(m.grain)
    limits = [
        f"{f.severity} · {f.node_id}: {f.message}" for f in result.findings if f.node_id in relevant
    ]
    if limits:
        description["limitations"] = "Offene Befunde: " + "; ".join(limits)

    contract: dict[str, Any] = {
        "apiVersion": API_VERSION,
        "kind": "DataContract",
        "id": slug(product.id),
        "name": product.name,
        "version": CONTRACT_VERSION,
        "status": CONTRACT_STATUS[product.status],
        "domain": index.workspace_name,
        "tags": ["lotse", product.kind],
    }
    if description:
        contract["description"] = description
    contract["schema"] = [_schema_object(t, measures, index, in_scope) for t in tables]
    contract["team"] = _team(product, measures, index)
    custom: list[dict[str, Any]] = [{"property": "lotseId", "value": product.id}]
    if decisions:
        custom.append(
            {
                "property": "decisions",
                "value": [{"id": d.id, "name": d.name} for d in decisions],
            }
        )
    custom.append({"property": "measures", "value": [_measure(m, index) for m in measures]})
    contract["customProperties"] = custom
    return contract


def dump(contract: dict[str, Any], workspace_name: str) -> str:
    header = (
        f"# Generiert von `lotse gen odcs` aus Workspace {workspace_name!r}.\n"
        "# Nicht von Hand bearbeiten: Änderungen gehören in die YAML-Dateien des Workspaces.\n"
    )
    body = yaml.safe_dump(
        contract, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100
    )
    return header + body


def generate(result: BuildResult) -> dict[str, str]:
    """Dateiname → Inhalt, ein Contract je Datenprodukt. Validiert jeden Contract."""
    index = Index(result)
    files: dict[str, str] = {}
    for product in index.all(Product):
        contract = build_contract(result, product)
        errors = validate(contract)
        if errors:
            raise OdcsError(f"{product.id}: ODCS-Schema verletzt:\n" + "\n".join(errors))
        files[f"{slug(product.id)}.odcs.yaml"] = dump(contract, index.workspace_name)
    return files
