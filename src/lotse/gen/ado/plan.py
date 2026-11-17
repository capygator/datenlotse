"""Backlog-Planung: Workspace → Work-Item-Plan (reine Logik, deterministisch, ohne Netzwerk).

Struktur:

- **Epic** je Datenprodukt (``product.*``).
- **Feature** je Kennzahl (``measure.*``), Parent ist das erste Datenprodukt (nach id), das sie
  führt. Weitere Datenprodukte stehen in der Beschreibung.
- **Feature** je Gold-Tabelle (``table.*``) einschließlich Quellanbindung; Quellen werden nicht
  als eigene Items geplant, sondern als Akzeptanzkriterien der Tabelle. Parent ist das erste
  Datenprodukt, das die Tabelle über Kennzahlen oder Dimensionen nutzt.
- **Story** je offenem Befund (Severity ``conflict``, ``gap``, ``warn``) und je offener Frage.
  Parent ist das Item des betroffenen Knotens (Dimension → erste Kennzahl mit dieser Dimension,
  Quelle → erste Tabelle aus dieser Quelle, Entscheidung → erstes Datenprodukt).

Jedes Item trägt einen stabilen Schlüssel aus der lotse-id (bzw. ``finding:<rule>:<node>``), der
als Tag ``lotse:<key>`` in ADO landet und Wiederholungen erkennbar macht. Der Plan ist
prozessneutral (Ebenen ``epic``/``feature``/``story``); Typnamen vergibt erst ``--process``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from lotse.model.entities import (
    Decision,
    Dimension,
    Measure,
    Product,
    Question,
    Source,
    Statement,
    Table,
)
from lotse.query import QUESTION_TEMPLATES
from lotse.store.build import BuildResult

FORMAT = "lotse-ado-backlog/1"
TAG_ROOT = "lotse"
TAG_SCOPE_PREFIX = "lotse-ws:"
TAG_KEY_PREFIX = "lotse:"
STORY_SEVERITIES = ("conflict", "gap", "warn")
"""Befunde dieser Severities werden zu Stories; ``info`` ist nicht handlungsrelevant."""

Level = Literal["epic", "feature", "story"]
LEVELS: tuple[Level, ...] = ("epic", "feature", "story")

FINDING_TITLES: dict[str, str] = {
    "measure_definition_conflict": "Definition von „{name}“ entscheiden",
    "missing_owner": "Owner für „{name}“ klären",
    "missing_grain": "Granularität für „{name}“ klären",
    "measure_without_table": "Datengrundlage für „{name}“ klären",
    "table_without_source": "Quelle für „{name}“ klären",
    "measure_without_decision": "Zweck von „{name}“ klären",
    "dimension_unused": "Verwendung von „{name}“ klären",
}

_KIND_LABEL = {
    "semantic_model": "Semantisches Modell",
    "report": "Report",
    "fact": "Faktentabelle",
    "dimension": "Dimensionstabelle",
}
_SCOPE_RE = re.compile(r"[^a-z0-9_-]+")


@dataclass(frozen=True)
class PlannedItem:
    key: str
    level: Level
    title: str
    parent: str | None
    origin: str
    description: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]

    def tags(self, scope: str) -> tuple[str, ...]:
        return (TAG_ROOT, scope_tag(scope), key_tag(self.key))

    def to_dict(self, scope: str) -> dict[str, Any]:
        return {
            "key": self.key,
            "level": self.level,
            "title": self.title,
            "parent": self.parent,
            "origin": self.origin,
            "tags": list(self.tags(scope)),
            "description": list(self.description),
            "acceptance_criteria": list(self.acceptance_criteria),
        }


@dataclass(frozen=True)
class Backlog:
    workspace: str
    scope: str
    items: tuple[PlannedItem, ...]

    def by_key(self) -> dict[str, PlannedItem]:
        return {i.key: i for i in self.items}

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "workspace": self.workspace,
            "scope": self.scope,
            "items": [i.to_dict(self.scope) for i in self.items],
        }

    def to_json(self) -> str:
        """Byte-stabile Serialisierung (feste Reihenfolge, LF, abschließender Zeilenumbruch)."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


def scope_tag(scope: str) -> str:
    return f"{TAG_SCOPE_PREFIX}{scope}"


def key_tag(key: str) -> str:
    return f"{TAG_KEY_PREFIX}{key}"


def normalize_scope(value: str) -> str:
    """Scope-Tag-Wert: Kleinbuchstaben, Ziffern, ``-``, ``_``."""
    slug = _SCOPE_RE.sub("-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"Ungültiger Scope: {value!r}")
    return slug


class _Planner:
    def __init__(self, result: BuildResult) -> None:
        self.models: dict[str, Any] = {e.id: e.model for e in result.loaded.entities}
        self.findings = result.findings

    # --- Zugriff -------------------------------------------------------------------------

    def of[T](self, cls: type[T]) -> list[T]:
        return [m for _, m in sorted(self.models.items()) if isinstance(m, cls)]

    def name(self, node_id: str) -> str:
        model = self.models.get(node_id)
        if model is None:
            return node_id
        value = getattr(model, "name", None) or getattr(model, "text", None) or node_id
        return str(value)

    def names(self, ids: list[str]) -> str:
        return ", ".join(self.name(i) for i in ids)

    def owner(self, node_id: str) -> str | None:
        owner = getattr(self.models.get(node_id), "owner", None)
        return self.name(owner) if owner else None

    def origin(self, statement_id: str | None) -> str | None:
        st = self.models.get(statement_id or "")
        if not isinstance(st, Statement):
            return None
        return f"„{st.text}“ ({self.name(st.by)}, {st.id})"

    # --- Zuordnung -----------------------------------------------------------------------

    def products_of_measure(self, measure_id: str) -> list[str]:
        return [p.id for p in self.of(Product) if measure_id in p.measures]

    def products_of_table(self, table_id: str) -> list[str]:
        dims = {d.id: d for d in self.of(Dimension)}
        result = []
        for p in self.of(Product):
            for mid in p.measures:
                m = self.models.get(mid)
                if not isinstance(m, Measure):
                    continue
                tables = set(m.from_tables)
                for did in m.grain:
                    if did in dims:
                        tables.update(dims[did].from_tables)
                if table_id in tables:
                    result.append(p.id)
                    break
        return result

    def users_of_table(self, table_id: str) -> tuple[list[str], list[str]]:
        measures = [m.id for m in self.of(Measure) if table_id in m.from_tables]
        dims = [d.id for d in self.of(Dimension) if table_id in d.from_tables]
        return measures, dims

    def anchor(self, node_id: str, planned: set[str]) -> str | None:
        """Item-Schlüssel, unter den ein Befund/eine Frage zu ``node_id`` gehängt wird."""
        if node_id in planned:
            return node_id
        model = self.models.get(node_id)
        candidates: list[str] = []
        if isinstance(model, Dimension):
            candidates = [m.id for m in self.of(Measure) if node_id in m.grain]
        elif isinstance(model, Source):
            candidates = [t.id for t in self.of(Table) if node_id in t.from_sources]
        elif isinstance(model, Decision):
            candidates = [p.id for p in self.of(Product) if node_id in p.serves]
        return next((c for c in candidates if c in planned), None)

    # --- Items ---------------------------------------------------------------------------

    def epic(self, p: Product) -> PlannedItem:
        lines = _opt(p.description)
        lines.append(f"Art: {_KIND_LABEL[p.kind]}")
        for did in p.serves:
            d = self.models.get(did)
            desc = f" ({d.description})" if isinstance(d, Decision) and d.description else ""
            lines.append(f"Stützt Entscheidung: {self.name(did)}{desc}")
        if p.measures:
            lines.append(f"Kennzahlen: {self.names(p.measures)}")
        lines += self._common(p.id, p.status, [p.statement])

        kind = _KIND_LABEL[p.kind]
        crit = [f"{kind} „{p.name}“ ist bereitgestellt."]
        if p.measures:
            crit.append(f"Alle {len(p.measures)} Kennzahlen sind enthalten und abgenommen.")
        crit += [f"Stützt die Entscheidung „{self.name(d)}“." for d in p.serves]
        crit += _acceptance_by(self.owner(p.id))
        return PlannedItem(
            p.id, "epic", f"Datenprodukt: {p.name}", None, p.id, tuple(lines), tuple(crit)
        )

    def measure_feature(self, m: Measure) -> PlannedItem:
        products = self.products_of_measure(m.id)
        lines = _opt(m.description)
        for d in m.definitions:
            lines.append(f"Definition ({self.name(d.by)}): {d.text}")
        if len({d.text for d in m.definitions}) > 1:
            lines.append("Achtung: abweichende Definitionen, Entscheidung offen.")
        if m.unit:
            lines.append(f"Einheit: {m.unit}")
        if m.grain:
            lines.append(f"Granularität: {self.names(m.grain)}")
        if m.time_logic:
            lines.append(f"Zeitlogik: {m.time_logic}")
        if m.from_tables:
            lines.append(f"Datengrundlage: {self.names(m.from_tables)}")
        if m.quality:
            lines.append(f"Qualitätsregeln: {', '.join(q.rule for q in m.quality)}")
        if m.serves:
            lines.append(f"Stützt Entscheidung: {self.names(m.serves)}")
        if len(products) > 1:
            lines.append(f"Auch in Datenprodukt: {self.names(products[1:])}")
        statements = [m.statement, *(d.statement for d in m.definitions)]
        lines += self._common(m.id, m.status, statements)

        texts = sorted({d.text for d in m.definitions})
        if len(texts) == 1:
            crit = [f"Berechnung entspricht der Definition: „{texts[0]}“."]
        else:
            crit = ["Eine abgestimmte Definition ist festgelegt (status: agreed)."]
        if m.grain:
            crit.append(f"Auswertbar je {self.names(m.grain)}.")
        if m.time_logic:
            crit.append(f"Zeitlogik umgesetzt: {m.time_logic}.")
        crit += [f"Qualitätsregel „{q.rule}“ ist geprüft." for q in m.quality]
        crit += _acceptance_by(self.owner(m.id))
        parent = products[0] if products else None
        return PlannedItem(
            m.id, "feature", f"Kennzahl: {m.name}", parent, m.id, tuple(lines), tuple(crit)
        )

    def table_feature(self, t: Table) -> PlannedItem:
        products = self.products_of_table(t.id)
        measures, dims = self.users_of_table(t.id)
        lines = _opt(t.description)
        lines.append(f"Art: {_KIND_LABEL[t.kind]}")
        for sid in t.from_sources:
            s = self.models.get(sid)
            if isinstance(s, Source):
                objects = f": {', '.join(s.objects)}" if s.objects else ""
                lines.append(f"Quelle: {s.name} ({s.system}{objects})")
            else:
                lines.append(f"Quelle: {sid}")
        if not t.from_sources:
            lines.append("Quelle: offen")
        if t.columns:
            cols = []
            for c in t.columns:
                extra = [c.type] + (["Schlüssel"] if c.key else [])
                if c.references:
                    extra.append(f"→ {self.name(c.references)}")
                cols.append(f"{c.name} ({', '.join(extra)})")
            lines.append(f"Spalten: {'; '.join(cols)}")
        if measures:
            lines.append(f"Genutzt von Kennzahlen: {self.names(measures)}")
        if dims:
            lines.append(f"Genutzt von Dimensionen: {self.names(dims)}")
        lines += self._common(t.id, t.status, [t.statement])

        crit = [f"Gold-Tabelle „{t.name}“ ist mit allen {len(t.columns)} Spalten bereitgestellt."]
        for sid in t.from_sources:
            s = self.models.get(sid)
            label = f"{s.name} ({s.system})" if isinstance(s, Source) else sid
            crit.append(f"Anbindung an {label} ist eingerichtet.")
        if not t.from_sources:
            crit.append("Quellsystem ist geklärt und angebunden.")
        crit += [f"Schlüssel „{c.name}“ ist eindeutig." for c in t.columns if c.key]
        crit += [
            f"Spalte „{c.name}“ verweist gültig auf „{self.name(c.references)}“."
            for c in t.columns
            if c.references
        ]
        crit += _acceptance_by(self.owner(t.id))
        parent = products[0] if products else None
        return PlannedItem(
            t.id, "feature", f"Tabelle: {t.name}", parent, t.id, tuple(lines), tuple(crit)
        )

    def finding_stories(self, planned: set[str]) -> list[PlannedItem]:
        grouped: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for f in self.findings:
            if f.severity in STORY_SEVERITIES and f.node_id:
                grouped.setdefault((f.rule, f.node_id), []).append((f.severity, f.message))
        items = []
        for (rule, node_id), entries in sorted(grouped.items()):
            name = self.name(node_id)
            title = FINDING_TITLES.get(rule, "Befund {rule} zu „{name}“ klären")
            lines = []
            for severity, message in sorted(set(entries)):
                question = QUESTION_TEMPLATES.get(rule, "{message}")
                lines.append(question.format(name=name, message=message))
                lines.append(f"Befund: [{severity}] {rule}: {message}")
            lines.append(f"Betrifft: {name} ({node_id})")
            if owner := self.owner(node_id):
                lines.append(f"Owner: {owner}")
            lines.append(_footer(node_id))
            crit = (
                "Antwort ist als Aussage (statement) im Workspace erfasst.",
                f"lotse check meldet {rule} für {node_id} nicht mehr.",
            )
            items.append(
                PlannedItem(
                    f"finding:{rule}:{node_id}",
                    "story",
                    title.format(name=name, rule=rule),
                    self.anchor(node_id, planned),
                    node_id,
                    tuple(lines),
                    crit,
                )
            )
        return items

    def question_story(self, q: Question, planned: set[str]) -> PlannedItem:
        lines = [f"Frage: {q.text}"]
        if q.about:
            lines.append(f"Betrifft: {self.names(q.about)}")
        if owner := self.owner(q.id):
            lines.append(f"Owner: {owner}")
        if origin := self.origin(q.statement):
            lines.append(f"Herkunft: {origin}")
        lines.append(_footer(q.id))
        crit = (
            "Antwort ist als Aussage erfasst und in der Frage eingetragen "
            "(answer, status: answered).",
            "Betroffene Entitäten sind im Workspace aktualisiert.",
        )
        parent = next((a for a in (self.anchor(i, planned) for i in q.about) if a), None)
        return PlannedItem(
            q.id, "story", f"Frage klären: {q.text}", parent, q.id, tuple(lines), crit
        )

    def _common(self, node_id: str, status: str, statements: list[str | None]) -> list[str]:
        lines = []
        if owner := self.owner(node_id):
            lines.append(f"Owner: {owner}")
        lines.append(f"Status: {status}")
        seen: list[str] = []
        for sid in statements:
            if sid and sid not in seen:
                seen.append(sid)
                if origin := self.origin(sid):
                    lines.append(f"Herkunft: {origin}")
        lines.append(_footer(node_id))
        return lines


def _opt(value: str | None) -> list[str]:
    return [value] if value else []


def _acceptance_by(owner: str | None) -> list[str]:
    return [f"Fachliche Abnahme durch {owner}."] if owner else []


def _footer(node_id: str) -> str:
    return f"Erzeugt von lotse aus {node_id}. Änderungen bitte im Workspace, nicht in ADO."


def _order(items: list[PlannedItem]) -> tuple[PlannedItem, ...]:
    """Tiefensuche: Parent vor Kindern; Geschwister nach Ebene, dann Schlüssel."""
    children: dict[str | None, list[PlannedItem]] = {}
    keys = {i.key for i in items}
    for item in items:
        parent = item.parent if item.parent in keys else None
        children.setdefault(parent, []).append(item)
    for group in children.values():
        group.sort(key=lambda i: (LEVELS.index(i.level), i.key))
    ordered: list[PlannedItem] = []

    def visit(parent: str | None) -> None:
        for item in children.get(parent, []):
            ordered.append(item)
            visit(item.key)

    visit(None)
    return tuple(ordered)


def plan_backlog(result: BuildResult, scope: str) -> Backlog:
    """Leitet den Backlog aus einem fehlerfreien Build ab."""
    if result.has_errors:
        raise ValueError("Workspace hat Befunde mit Severity error; Backlog wird nicht geplant.")
    p = _Planner(result)
    items: list[PlannedItem] = [p.epic(prod) for prod in p.of(Product)]
    items += [p.measure_feature(m) for m in p.of(Measure)]
    items += [p.table_feature(t) for t in p.of(Table)]
    planned = {i.key for i in items}
    items += p.finding_stories(planned)
    items += [p.question_story(q, planned) for q in p.of(Question) if q.status == "open"]
    cfg = result.loaded.config
    workspace = cfg.name if cfg else result.workspace.name
    return Backlog(workspace, normalize_scope(scope), _order(items))
