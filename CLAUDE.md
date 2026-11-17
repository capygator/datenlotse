# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stand

`lotse-konzept.md` ist Konzept und Bauauftrag (Meilensteine M1–M6, §11). Bei Widerspruch zwischen Code-Doku und Konzept: nachfragen, nicht raten.

## Befehle

```bash
uv sync                                         # Umgebung (Python 3.12, .python-version)
uv run pytest                                   # alle Tests
uv run pytest tests/test_rules.py::test_missing_grain_positive   # einzelner Test
uv run ruff check . && uv run ruff format --check .
uv run mypy src/lotse                           # strict über pyproject
uv run lotse check -w demo/nordwind             # Exit 1 bei error-Befunden
uv run lotse schema                             # schemas/*.json nach Modelländerung neu erzeugen
uv run lotse serve -w demo/nordwind --no-open   # Live-Viewer auf http://127.0.0.1:8765/
uv run lotse render archify --view lineage -w demo/nordwind   # → demo/nordwind/out/lineage.json
LOTSE_UPDATE_SNAPSHOTS=1 uv run pytest tests/test_generators.py  # Generator-Snapshots neu schreiben
```

CLI: `init <name> [--root workspaces]`, `build`, `check`, `next [--json]`, `status [--json]`, `schema`, `render <mermaid|archify> --view <name>`, `render views`, `serve [--host 127.0.0.1] [--port 8765] [--open/--no-open]`, `gen <odcs|tmdl>`, `gen ado [--apply --org … --project … --process agile|scrum]`. Ausgabe von `render`/`gen` standardmäßig nach `<workspace>/out/` (gitignored), `-o DIR` überschreibt; `gen` schreibt in `<out>/<generator>/` und ersetzt dort nur eigene Ausgaben (Projektordner je Produkt bzw. `*.odcs.yaml`). Workspace über `-w PATH`, sonst Suche nach `lotse.yaml` vom aktuellen Ordner aufwärts.

## Architektur

- **YAML in Git ist die Wahrheit.** Ein Workspace ist ein Ordner mit `lotse.yaml` und je einem Unterordner pro Entitätstyp (`decisions/` … `questions/`). Referenz-Workspace: `demo/nordwind/` (Endzustand nach Akt 5; ein offener `gap` bei `table.fact_lieferzusage` ist gewollt).
- **DuckDB ist Cache.** `store/build.py` löscht `<workspace>/.lotse/lotse.duckdb` und baut alles neu: `loader.py` (YAML → Pydantic, Ladefehler als `schema`-Befunde) → `graph.py` (Knoten, Kanten, Attribute, Definitionen) → Tabellen `node`, `edge`, `attr`, `definition`, `finding` plus Lookups `stage`, `severity`, `workspace`.
- **Modell = einzige Schema-Quelle.** `model/entities.py` (Pydantic, `extra="forbid"`, Feldreihenfolge = kanonische YAML-Schlüsselreihenfolge); ID-Felder sind per Regex auf ihren Typ festgelegt (`serves` nur `decision.*`). `schemas/*.json` wird daraus generiert, `tests/test_schema.py` prüft Gleichstand.
- **Kanten** entstehen aus `graph.REF_FIELDS` (Kantenart = Feldname) plus `definition_by`, `definition_statement`, `column_references`. Neues ID-Feld → in `REF_FIELDS` aufnehmen, sonst fehlt es in `dangling_reference`.
- **Regeln** sind `src/lotse/rules/*.sql`, eine pro Datei, Spalten `rule, severity, node_id, message`; `rule` muss dem Dateinamen entsprechen (wird geprüft). Severities in Rangfolge: `error`, `conflict`, `gap`, `warn`, `info` (`model/registry.py`).
- **`query.py`**: `next_question` (Fehler zuerst, dann frühere Stufe, dann Severity; Fragetext aus `QUESTION_TEMPLATES`) und `stage_status`. `next` und `status` bauen vorher immer neu.
- **`gen/ado/`** (M6): `plan.py` Workspace → Backlog (Epic je Produkt, Feature je Kennzahl und Tabelle, Story je Befund `conflict|gap|warn` und offener Frage), rein und byte-stabil nach `<ws>/out/ado/backlog.json`; `sync.py` idempotenter Abgleich gegen das Protokoll `WorkItemStore` (Tags `lotse-ws:<scope>` + `lotse:<key>`); `rest.py` einzige Stelle mit ADO-REST-Details (stdlib `urllib`). REST statt MCP ist entschieden (2026-11-17). Details und Abnahme-Anleitung: `docs/ado.md`.
- **Live-Pfad** (`serve/`): `app.py` startet per Lifespan einen `watchfiles`-Wächter (nur `*.yaml`, `.lotse/` ignoriert) → voller Neubau in eigene Datei `.lotse/serve.duckdb` (kollidiert nicht mit parallelen CLI-Läufen) → `state.make_snapshot` (Knoten mit Darstellungsstatus und Inhalts-Hash, Kanten, Befunde, Stufen) → `diff.diff_snapshots` (reine Logik) → SSE an alle Clients. API liest nur die gecachte Momentaufnahme, nie DuckDB. Darstellungsstatus: Befund `error`/`conflict`/`gap` schlägt YAML-`status`, `warn`/`info` nicht.
- **Endpunkte**: `GET /` (Viewer), `GET /api/graph` (Stand inkl. Befunde, Stufen, `version`, `caption`), `GET /api/node/{id}` (Definitionen, Herkunft, offene Fragen, Nachbarn), `GET /api/events` (SSE: `snapshot` beim Verbinden, dann `diff` und `caption`), `POST /api/caption` (`{question, answer, text}`, leerer Body löscht; für Einblendungen im Replay, M3). Einblendung ist reiner Anzeigezustand, nicht Teil des Modells.
- **Viewer**: `src/lotse/viewer/index.html` (im Paket, geladen per `importlib.resources`; Konzept nennt `viewer/`). Eine Seite ohne Build, Cytoscape.js 3.30.2 + elkjs 0.9.3 + cytoscape-elk 2.2.0 im Paket unter `viewer/vendor/` (offline, Lizenzen daneben, ausgeliefert über `GET /vendor/{name}`); Spalten über ELK-Partitionierung (Stufe = Partition), ohne ELK Ersatzlayout in festen Spalten. Schreibt nichts außer optional Theme in `localStorage`.
- **Sichten** sind `src/lotse/views/*.sql` mit Kopf `-- title:`, `-- kind: flow|erd`, `-- description:` und festen Spalten (`views/__init__.py`: `element, id, label, sublabel, lane, lane_label, status, finding, src, dst, detail`). `lineage` fasst Kennzahlen je Owner zu Blöcken zusammen (Archify ≤ 12 Knoten), `lineage_detail` zeigt jede Kennzahl, `model` liefert Tabellen + Fremdschlüssel. Spaltenreihenfolge kommt aus `pos` im `column`-Attribut.
- **Renderer** (`src/lotse/render/`) implementieren `Renderer.render(ViewResult) -> str`; `archify` validiert gegen die vendorten Schemas (`render/schemas/archify/`, Archify 3.2.0), `flow` → `dataflow` (max. 5 Stufen), `erd` → `erd`.
- **Generatoren** (`src/lotse/gen/`) bauen vorher neu und brechen bei `error`-Befunden ab; sie lesen die Pydantic-Entitäten aus `BuildResult` und liefern `{relativer Pfad: Text}`. Neue Befehle in `gen/cli.py` (`gen_app`) ergänzen; Untergruppen importieren aus `cli_common.py`, nie aus `cli.py`. `odcs` validiert gegen `gen/schemas/odcs-json-schema-v3.1.0.json` (Tag v3.1.0, Quelle in `gen/schemas/README.md`). `tmdl` erzeugt je Produkt ein PBIP (SemanticModel in TMDL + leerer PBIR-Bericht); lineageTags = UUIDv5 aus der lotse-id; Format entspricht byte-genau dem Roundtrip durch Microsofts `TmdlSerializer`.
- **Stufen**: Entscheidung → Datenprodukt → Kennzahl → Dimension → Tabelle → Quelle (`registry.ENTITY_TYPES`); Stakeholder, Aussagen und Fragen haben keine Stufe.

## Invarianten

- Kein Zustand, der nur in DuckDB, im Viewer oder im Chatverlauf existiert.
- Eine Datei pro Entität, Dateiname = Slug der `id` (`measures/umsatz.yaml` ↔ `measure.umsatz`); `id` ändert sich nie.
- Keine Zeitstempel im YAML-Inhalt. Fachliche Angaben verweisen per `statement` auf ihre Herkunft.
- Konflikt = mehrere abweichende `definitions`. Nie automatisch glätten; Einigung = auf einen Eintrag reduzieren + `status: agreed`.
- Kern deterministisch, Generatoren byte-stabil. Kein Schreiben nach Fabric/ADO ohne `--apply`.
- Tests ohne Netzwerk; Demo offline.

## Tests

`tests/conftest.py` stellt `BASE` (befundfreier Mini-Workspace) und das Fixture `run` bereit; Regeltests mutieren `BASE` (je Regel positiv + negativ). `test_nordwind.py` fixiert die exakte Befundliste und prüft Determinismus des Neubaus. `test_gen_ado.py`: Snapshot `tests/snapshots/ado/` (neu schreiben mit `LOTSE_UPDATE_SNAPSHOTS=1`), `--apply` gegen `tests/ado_fake.py` (simuliertes ADO auf HTTP-Ebene). `test_serve_live.py` startet echten uvicorn in einem Thread und misst Speichern → SSE-Diff (< 2 s); SSE nie über `TestClient` testen (unendlicher Stream). Dev-Abhängigkeit `httpx2` (Starlette-TestClient). `test_generators.py` vergleicht alle Render-/Generator-Ausgaben byte-genau mit `tests/snapshots/nordwind/` und prüft zwei Läufe auf Gleichheit.

## Offene Entscheidungen (nicht eigenmächtig treffen, nachfragen)

- DPU_REQ-Excel als Import/Export?
- Siebter Entitätstyp `rule`, falls in echten Sessions > ⅓ der Aussagen im Freitext landet.
