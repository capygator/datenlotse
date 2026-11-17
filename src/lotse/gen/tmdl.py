"""TMDL-Generator: ein Power-BI-Projekt (PBIP) mit TMDL-Modell je Datenprodukt.

Ausgabe je Produkt unter ``tmdl/<slug>/``::

    <slug>.pbip
    <slug>.SemanticModel/definition.pbism
    <slug>.SemanticModel/definition/{database,model,relationships}.tmdl
    <slug>.SemanticModel/definition/tables/<Tabelle>.tmdl
    <slug>.Report/definition.pbir + definition/ (leere Berichtsseite, PBIR)

Syntax nach Microsoft Learn „TMDL overview“: Tabs zur Einrückung, Namen mit Sonderzeichen in
einfachen Anführungszeichen, Beschreibungen per ``///``. lineageTags und Beziehungsnamen sind
UUIDv5 aus der lotse-id (deterministisch). Jede Tabelle bekommt eine Import-Partition mit
leerer typisierter M-Tabelle (``#table``), damit das Modell ohne Datenquelle öffnet.
Kennzahlen werden Platzhalter-Measures (``BLANK()``) mit Definitionstext als Beschreibung.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from lotse.gen.common import Index, key_column, product_scope, slug, stable_uuid
from lotse.model.entities import Column, Dimension, Measure, Product, Source, Stakeholder, Table
from lotse.store.build import BuildResult

FOLDER = "tmdl"
COMPATIBILITY_LEVEL = 1567
CULTURE = "de-DE"
MEASURE_TABLE = "Kennzahlen"

DATA_TYPE = {
    "string": "string",
    "int64": "int64",
    "decimal": "decimal",
    "double": "double",
    "date": "dateTime",
    "datetime": "dateTime",
    "boolean": "boolean",
}
M_TYPE = {
    "string": "text",
    "int64": "Int64.Type",
    "decimal": "Currency.Type",
    "double": "number",
    "date": "date",
    "datetime": "datetime",
    "boolean": "logical",
}
NUMERIC = {"int64", "decimal", "double"}


def quote(name: str) -> str:
    """TMDL-Objektname; in ``'…'`` bei Punkt, Gleich, Doppelpunkt, Apostroph oder Leerraum."""
    if name and not re.search(r"[.=:'\s]", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def m_name(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return name
    return '#"' + name.replace('"', '""') + '"'


def file_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name) + ".tmdl"


def description(lines: list[str], indent: str) -> list[str]:
    out = []
    for line in lines:
        for part in line.splitlines():
            if part.strip():
                out.append(f"{indent}/// {part.strip()}")
    return out


def format_string(unit: str | None) -> str:
    if unit == "%":
        return "0.0 %"
    if unit == "EUR":
        return "#,##0 €"
    return "#,##0.00"


@dataclass
class TmdlMeasure:
    name: str
    measure: Measure


@dataclass
class TmdlTable:
    name: str
    table: Table | None
    measures: list[TmdlMeasure] = field(default_factory=list)


def _measure_lines(tm: TmdlMeasure, index: Index) -> list[str]:
    m = tm.measure
    desc = [f"Platzhalter: DAX noch nicht umgesetzt (lotse: {m.id}, Status: {m.status})."]
    for d in m.definitions:
        who = index.get(d.by, Stakeholder)
        desc.append(f"Definition ({who.name if who else d.by}): {d.text}")
    if not m.definitions:
        desc.append("Definition: offen")
    facts = []
    if m.unit:
        facts.append(f"Einheit: {m.unit}")
    if m.time_logic:
        facts.append(f"Zeitlogik: {m.time_logic}")
    grain = [(dim.name if (dim := index.get(g, Dimension)) else g) for g in m.grain]
    if grain:
        facts.append("Grain: " + ", ".join(grain))
    if facts:
        desc.append(" · ".join(facts))
    if m.quality:
        desc.append("Qualität: " + ", ".join(q.rule for q in m.quality))
    lines = description(desc, "\t")
    lines.append(f"\tmeasure {quote(tm.name)} = BLANK()")
    lines.append(f"\t\tformatString: {format_string(m.unit)}")
    lines.append(f"\t\tlineageTag: {stable_uuid(m.id)}")
    lines.append("")
    lines.append(f"\t\tannotation lotse_id = {m.id}")
    lines.append("")
    return lines


def _column_lines(table: Table, col: Column, hidden: bool) -> list[str]:
    lines = description([col.description] if col.description else [], "\t")
    lines.append(f"\tcolumn {quote(col.name)}")
    # Eigenschaftsreihenfolge wie TmdlSerializer (Roundtrip ohne Diff).
    lines.append(f"\t\tdataType: {DATA_TYPE[col.type]}")
    if hidden:
        lines.append("\t\tisHidden")
    if col.key and key_column(table) == col.name:
        lines.append("\t\tisKey")
    if col.type == "date":
        lines.append("\t\tformatString: Long Date")
    elif col.type == "datetime":
        lines.append("\t\tformatString: General Date")
    lines.append(f"\t\tlineageTag: {stable_uuid(f'{table.id}#{col.name}')}")
    additive = table.kind == "fact" and col.type in NUMERIC
    summarize = "sum" if additive and not col.key and not col.references else "none"
    lines.append(f"\t\tsummarizeBy: {summarize}")
    lines.append(f"\t\tsourceColumn: {col.name}")
    if col.type == "date":
        lines.append("")
        lines.append("\t\tannotation UnderlyingDateTimeDataType = Date")
    lines.append("")
    return lines


def _partition_lines(tt: TmdlTable, index: Index) -> list[str]:
    table = tt.table
    if table is None:
        return [
            f"\tpartition {quote(tt.name)} = calculated",
            "\t\tmode: import",
            '\t\tsource = ROW("Platzhalter", BLANK())',
            "",
        ]
    fields = ", ".join(f"{m_name(c.name)} = {M_TYPE[c.type]}" for c in table.columns)
    sources = [
        f"{s.name} ({s.system})"
        for sid in table.from_sources
        if (s := index.get(sid, Source)) is not None
    ]
    origin = ", ".join(sources) if sources else "offen"
    return [
        f"\tpartition {quote(tt.name)} = m",
        "\t\tmode: import",
        "\t\tsource =",
        "\t\t\t\tlet",
        f"\t\t\t\t\t// Platzhalter aus lotse ({table.id}), Quelle: {origin}",
        f"\t\t\t\t\tQuelle = #table(type table [{fields}], {{}})",
        "\t\t\t\tin",
        "\t\t\t\t\tQuelle",
        "",
    ]


def _table_text(tt: TmdlTable, fk_columns: set[str], index: Index) -> str:
    table = tt.table
    lines: list[str] = []
    if table is not None:
        desc = [table.description] if table.description else []
        desc.append(f"lotse: {table.id} ({table.kind}, Status: {table.status})")
        lines += description(desc, "")
        lines.append(f"table {quote(tt.name)}")
        lines.append(f"\tlineageTag: {stable_uuid(table.id)}")
    else:
        lines += description(["Kennzahlen ohne Gold-Tabelle (Platzhalter)."], "")
        lines.append(f"table {quote(tt.name)}")
        lines.append(f"\tlineageTag: {stable_uuid('table:' + MEASURE_TABLE)}")
    lines.append("")
    for tm in tt.measures:
        lines += _measure_lines(tm, index)
    if table is not None:
        for col in table.columns:
            lines += _column_lines(table, col, col.name in fk_columns)
    else:
        lines += [
            "\tcolumn Platzhalter",
            "\t\tdataType: string",
            "\t\tisHidden",
            f"\t\tlineageTag: {stable_uuid('column:' + MEASURE_TABLE)}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: [Platzhalter]",
            "",
        ]
    lines += _partition_lines(tt, index)
    return "\n".join(lines).rstrip("\n") + "\n\n"


@dataclass(frozen=True)
class Relationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    active: bool


def _relationships(tables: list[Table], names: dict[str, str]) -> list[Relationship]:
    by_id = {t.id: t for t in tables}
    rels: list[Relationship] = []
    pairs: set[tuple[str, str]] = set()
    for t in tables:
        for col in t.columns:
            target = by_id.get(col.references or "")
            if target is None or target.id == t.id:
                continue
            to_col = key_column(target)
            to = next((c for c in target.columns if c.name == to_col), None)
            if to is None or DATA_TYPE[to.type] != DATA_TYPE[col.type]:
                continue
            pair = (t.id, target.id)
            rels.append(
                Relationship(names[t.id], col.name, names[target.id], to.name, pair not in pairs)
            )
            pairs.add(pair)
    return rels


def _relationship_text(rels: list[Relationship], product: Product) -> str:
    lines: list[str] = []
    for r in rels:
        key = f"{product.id}|{r.from_table}.{r.from_column}->{r.to_table}.{r.to_column}"
        lines.append(f"relationship {stable_uuid(key)}")
        if not r.active:
            lines.append("\tisActive: false")
        lines.append(f"\tfromColumn: {quote(r.from_table)}.{quote(r.from_column)}")
        lines.append(f"\ttoColumn: {quote(r.to_table)}.{quote(r.to_column)}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n\n" if lines else ""


def _model_text(tables: list[TmdlTable], product: Product) -> str:
    lines = description([f"{product.name} (lotse: {product.id})"], "")
    lines += [
        "model Model",
        f"\tculture: {CULTURE}",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures",
        f"\tsourceQueryCulture: {CULTURE}",
        "",
    ]
    lines += [f"ref table {quote(t.name)}" for t in tables]
    return "\n".join(lines) + "\n\n"


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _report_files(name: str) -> dict[str, str]:
    base = "https://developer.microsoft.com/json-schemas/fabric/item/report"
    page = "lotse0000000000000000"
    return {
        f"{name}.Report/definition.pbir": _json(
            {
                "$schema": f"{base}/definitionProperties/2.0.0/schema.json",
                "version": "4.0",
                "datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}},
            }
        ),
        f"{name}.Report/definition/version.json": _json(
            {"$schema": f"{base}/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"}
        ),
        f"{name}.Report/definition/report.json": _json(
            {
                "$schema": f"{base}/definition/report/1.0.0/schema.json",
                "themeCollection": {},
                "layoutOptimization": "None",
            }
        ),
        f"{name}.Report/definition/pages/pages.json": _json(
            {
                "$schema": f"{base}/definition/pagesMetadata/1.0.0/schema.json",
                "pageOrder": [page],
                "activePageName": page,
            }
        ),
        f"{name}.Report/definition/pages/{page}/page.json": _json(
            {
                "$schema": f"{base}/definition/page/1.0.0/schema.json",
                "name": page,
                "displayName": "Seite 1",
                "displayOption": "FitToPage",
                "height": 720,
                "width": 1280,
            }
        ),
    }


def _unique(name: str, taken: set[str]) -> str:
    candidate, n = name, 2
    while candidate.casefold() in taken:
        candidate = f"{name} ({n})"
        n += 1
    taken.add(candidate.casefold())
    return candidate


def project(result: BuildResult, product: Product) -> dict[str, str]:
    """Dateien eines PBIP-Projekts (Pfad relativ zum Projektordner → Inhalt)."""
    index = Index(result)
    measures, tables = product_scope(index, product)
    taken: set[str] = set()
    names = {t.id: _unique(t.name, taken) for t in tables}
    tmdl_tables = {t.id: TmdlTable(names[t.id], t) for t in tables}

    # Measure-Namen sind modellweit eindeutig und dürfen keiner Spalte der Heimtabelle gleichen.
    measure_names: set[str] = {n.casefold() for n in names.values()}
    homeless = TmdlTable(_unique(MEASURE_TABLE, taken), None)
    for m in measures:
        home_id = next((tid for tid in m.from_tables if tid in tmdl_tables), None)
        home = tmdl_tables[home_id] if home_id else homeless
        cols = {c.name.casefold() for c in home.table.columns} if home.table else {"platzhalter"}
        name = _unique(m.name, measure_names | cols)
        measure_names.add(name.casefold())
        home.measures.append(TmdlMeasure(name, m))

    ordered = [tmdl_tables[t.id] for t in tables]
    if homeless.measures:
        ordered.append(homeless)

    rels = _relationships(tables, names)
    fk_columns: dict[str, set[str]] = {}
    for r in rels:
        fk_columns.setdefault(r.from_table, set()).add(r.from_column)

    name = slug(product.id)
    sm = f"{name}.SemanticModel"
    files: dict[str, str] = {
        f"{name}.pbip": _json(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                "version": "1.0",
                "artifacts": [{"report": {"path": f"{name}.Report"}}],
                "settings": {"enableAutoRecovery": True},
            }
        ),
        f"{sm}/definition.pbism": _json(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
                "version": "4.2",
                "settings": {},
            }
        ),
        f"{sm}/definition/database.tmdl": (
            f"database {stable_uuid(product.id)}\n\tcompatibilityLevel: {COMPATIBILITY_LEVEL}\n\n"
        ),
        f"{sm}/definition/model.tmdl": _model_text(ordered, product),
    }
    rel_text = _relationship_text(rels, product)
    if rel_text:
        files[f"{sm}/definition/relationships.tmdl"] = rel_text
    for tt in ordered:
        files[f"{sm}/definition/tables/{file_name(tt.name)}"] = _table_text(
            tt, fk_columns.get(tt.name, set()), index
        )
    files.update(_report_files(name))
    return files


def generate(result: BuildResult) -> dict[str, str]:
    """Alle Projekte: Pfad relativ zum ``tmdl``-Ordner → Inhalt."""
    index = Index(result)
    files: dict[str, str] = {}
    for product in index.all(Product):
        for rel, text in project(result, product).items():
            files[f"{slug(product.id)}/{rel}"] = text
    return files
