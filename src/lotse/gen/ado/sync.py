"""Abgleich eines geplanten Backlogs mit einem Work-Item-Speicher (idempotent).

Der Speicher steht hinter dem Protokoll :class:`WorkItemStore`. Die REST-Umsetzung liegt in
``rest.py``; ein späterer MCP-Weg implementiert dasselbe Protokoll, Planung und Abgleich bleiben
unverändert.

Idempotenz: Alle von lotse verwalteten Items tragen den Scope-Tag ``lotse-ws:<scope>`` und den
Schlüssel-Tag ``lotse:<key>``. Vor dem Schreiben werden alle Items des Scopes geladen und per
exaktem Tag-Vergleich ihrem Schlüssel zugeordnet. Existiert ein Item, werden nur abweichende
Felder aktualisiert; ein Parent-Link wird nur gesetzt, wenn noch keiner existiert. Items, die
nicht mehr im Plan stehen, bleiben unangetastet und werden gemeldet.
"""

from __future__ import annotations

import html
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from lotse.gen.ado.plan import TAG_KEY_PREFIX, Backlog, Level, PlannedItem, scope_tag

Process = Literal["agile", "scrum"]

PROCESS_TYPES: dict[Process, dict[Level, str]] = {
    "agile": {"epic": "Epic", "feature": "Feature", "story": "User Story"},
    "scrum": {"epic": "Epic", "feature": "Feature", "story": "Product Backlog Item"},
}

F_TITLE = "System.Title"
F_DESCRIPTION = "System.Description"
F_TAGS = "System.Tags"
F_AREA = "System.AreaPath"
F_ITERATION = "System.IterationPath"
F_ACCEPTANCE = "Microsoft.VSTS.Common.AcceptanceCriteria"
MANAGED_FIELDS = (F_TITLE, F_DESCRIPTION, F_ACCEPTANCE)
TITLE_MAX = 255


class AdoError(Exception):
    """Fehler beim Zugriff auf Azure DevOps (Meldung enthält nie den PAT)."""


@dataclass(frozen=True)
class RemoteItem:
    id: int
    type: str
    fields: dict[str, str]
    tags: tuple[str, ...]
    parent_id: int | None


class WorkItemStore(Protocol):
    """Kleinste Schnittstelle zu einem ADO-Projekt."""

    def work_item_types(self) -> set[str]: ...

    def find_managed(self, scope_tag: str) -> list[RemoteItem]:
        """Alle Items, die den Tag ``scope_tag`` tragen (Obermenge erlaubt)."""
        ...

    def create(
        self, type_name: str, fields: dict[str, str], parent_id: int | None
    ) -> RemoteItem: ...

    def update(self, item_id: int, fields: dict[str, str]) -> None: ...

    def set_parent(self, item_id: int, parent_id: int) -> None: ...


@dataclass(frozen=True)
class Target:
    process: Process = "agile"
    area: str | None = None
    iteration: str | None = None

    def type_of(self, level: Level) -> str:
        return PROCESS_TYPES[self.process][level]


@dataclass
class SyncReport:
    created: list[tuple[str, int]] = field(default_factory=list)
    updated: list[tuple[str, int, tuple[str, ...]]] = field(default_factory=list)
    linked: list[tuple[str, int, int]] = field(default_factory=list)
    unchanged: list[tuple[str, int]] = field(default_factory=list)
    stale: list[tuple[str, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def writes(self) -> int:
        return len(self.created) + len(self.updated) + len(self.linked)


# --- Feldinhalte -------------------------------------------------------------------------


def truncate_title(title: str) -> str:
    """Einzeilig (ADO-Titel erlauben keine Zeilenumbrüche), höchstens 255 Zeichen."""
    title = " ".join(title.split())
    return title if len(title) <= TITLE_MAX else title[: TITLE_MAX - 1].rstrip() + "…"


def _html_list(lines: Iterable[str]) -> str:
    return "<ul>" + "".join(f"<li>{html.escape(x, quote=False)}</li>" for x in lines) + "</ul>"


def render_fields(item: PlannedItem) -> dict[str, str]:
    """Verwaltete Felder eines Items. Akzeptanzkriterien als eigenes Feld nur auf Story-Ebene
    (dort in Agile und Scrum vorhanden), bei Epic/Feature als Abschnitt der Beschreibung."""
    desc = "".join(f"<p>{html.escape(x, quote=False)}</p>" for x in item.description)
    fields = {F_TITLE: truncate_title(item.title)}
    if item.level == "story":
        fields[F_DESCRIPTION] = desc
        fields[F_ACCEPTANCE] = _html_list(item.acceptance_criteria)
    else:
        fields[F_DESCRIPTION] = (
            desc + "<p><b>Akzeptanzkriterien</b></p>" + _html_list(item.acceptance_criteria)
        )
    return fields


def split_tags(value: str | None) -> tuple[str, ...]:
    return tuple(t.strip() for t in (value or "").split(";") if t.strip())


def join_tags(tags: Iterable[str]) -> str:
    return "; ".join(tags)


def merge_tags(existing: tuple[str, ...], planned: tuple[str, ...]) -> tuple[str, ...] | None:
    """Vorhandene Tags behalten, fehlende ergänzen. ``None``, wenn nichts fehlt."""
    have = {t.lower() for t in existing}
    missing = [t for t in planned if t.lower() not in have]
    return (*existing, *missing) if missing else None


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip() == (b or "").strip()


# --- Abgleich ----------------------------------------------------------------------------


def index_remote(items: list[RemoteItem], scope: str, report: SyncReport) -> dict[str, RemoteItem]:
    """Schlüssel → Item, exakter Tag-Vergleich. Bei Duplikaten gewinnt die kleinste id."""
    wanted_scope = scope_tag(scope).lower()
    found: dict[str, list[RemoteItem]] = {}
    for item in items:
        lowered = [t.lower() for t in item.tags]
        if wanted_scope not in lowered:
            continue
        for tag in item.tags:
            if tag.lower().startswith(TAG_KEY_PREFIX):
                found.setdefault(tag[len(TAG_KEY_PREFIX) :], []).append(item)
    result: dict[str, RemoteItem] = {}
    for key in sorted(found):
        group = sorted(found[key], key=lambda i: i.id)
        result[key] = group[0]
        if len(group) > 1:
            others = ", ".join(f"#{i.id}" for i in group[1:])
            report.warnings.append(
                f"{key}: mehrere Items mit demselben Schlüssel, verwende #{group[0].id} "
                f"(Duplikate: {others})"
            )
    return result


def check_types(store: WorkItemStore, target: Target) -> None:
    available = store.work_item_types()
    needed = sorted(set(PROCESS_TYPES[target.process].values()))
    missing = [t for t in needed if t not in available]
    if missing:
        other = "scrum" if target.process == "agile" else "agile"
        raise AdoError(
            f"Work-Item-Typen fehlen im Projekt: {', '.join(missing)}. "
            f"Passt --process {target.process}? (Alternative: --process {other})"
        )


def sync(backlog: Backlog, store: WorkItemStore, target: Target) -> SyncReport:
    """Schreibt den Plan idempotent in den Speicher. Reihenfolge: Parent vor Kindern."""
    report = SyncReport()
    check_types(store, target)
    remote = index_remote(store.find_managed(scope_tag(backlog.scope)), backlog.scope, report)
    ids: dict[str, int] = {}

    for item in backlog.items:
        type_name = target.type_of(item.level)
        fields = render_fields(item)
        tags = item.tags(backlog.scope)
        parent_id = ids.get(item.parent) if item.parent else None
        if item.parent and parent_id is None:
            report.warnings.append(f"{item.key}: Parent {item.parent} hat keine Work-Item-ID")

        existing = remote.get(item.key)
        if existing is None:
            create_fields = {**fields, F_TAGS: join_tags(tags)}
            if target.area:
                create_fields[F_AREA] = target.area
            if target.iteration:
                create_fields[F_ITERATION] = target.iteration
            created = store.create(type_name, create_fields, parent_id)
            ids[item.key] = created.id
            report.created.append((item.key, created.id))
            continue

        ids[item.key] = existing.id
        if existing.type != type_name:
            report.warnings.append(
                f"{item.key}: #{existing.id} ist {existing.type}, geplant {type_name}; "
                "Typ wird nicht geändert"
            )
        changes = {k: v for k, v in fields.items() if not _same(existing.fields.get(k), v)}
        merged = merge_tags(existing.tags, tags)
        if merged is not None:
            changes[F_TAGS] = join_tags(merged)
        if changes:
            store.update(existing.id, changes)
            report.updated.append((item.key, existing.id, tuple(sorted(changes))))

        if parent_id is not None:
            if existing.parent_id is None:
                store.set_parent(existing.id, parent_id)
                report.linked.append((item.key, existing.id, parent_id))
            elif existing.parent_id != parent_id:
                report.warnings.append(
                    f"{item.key}: #{existing.id} hängt unter #{existing.parent_id}, "
                    f"geplant #{parent_id}; Hierarchie bleibt unverändert"
                )
        if not changes and not (parent_id is not None and existing.parent_id is None):
            report.unchanged.append((item.key, existing.id))

    planned = backlog.by_key()
    report.stale = [(k, r.id) for k, r in sorted(remote.items()) if k not in planned]
    return report
