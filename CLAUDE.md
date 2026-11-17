# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stand

Pre-Implementation. Einzige Quelle ist `lotse-konzept.md` (Konzept und Bauauftrag für `lotse`, Status draft). Noch kein Code, kein Git-Repo. Bei Widerspruch zwischen dieser Datei und dem Konzept gilt das Konzept.

Nächster Schritt laut Konzept: **M1** umsetzen. Mit dem Nordwind-Endzustand (`demo/nordwind/`) als Fixture beginnen und daraus Schema und Regeln ableiten.

## Stack (geplant)

Python 3.12, `uv`, Typer (CLI), Pydantic (Modelle + JSON-Schema-Export), DuckDB (Python-API), FastAPI + Server-Sent Events, Cytoscape.js mit ELK-Layout. Der Viewer ist eine einzelne HTML-Seite ohne Build-Schritt.

## Befehle (Zielzustand, existieren erst nach Projekt-Setup)

```bash
uv run pytest                                  # alle Tests
uv run pytest tests/<datei>.py::<test>         # einzelner Test
uv run ruff check
uv run mypy --strict src/lotse
```

CLI `lotse`: `init <name>`, `build`, `check` (Exit ≠ 0 bei `error`, für Hook und CI), `next [--json]`, `status`, `serve`, `render <mermaid|archify> --view <name>`, `gen <odcs|tmdl|ado>` (`ado --apply` schreibt nach ADO), `demo [--replay] [--auto] [--record]`. Details: Konzept §8.

## Architektur

- **YAML in Git ist die Wahrheit.** Ein Workspace (`workspaces/<name>/`) ist ein Ordner mit `lotse.yaml` und je einem Unterordner pro Entitätstyp.
- **DuckDB ist Cache.** `lotse build` baut `.lotse/lotse.duckdb` immer vollständig aus den Dateien neu (gitignored).
- **Datenfluss:** YAML → Schema-Validierung → Tabellen `node`, `edge`, `attr`, `definition` → Regeln → `finding` → konsumiert von `lotse next`, Live-Viewer und Generatoren.
- **Regeln** liegen als `src/lotse/rules/*.sql`, eine Regel pro Datei, jede liefert Zeilen im Format `finding(rule, severity, node_id, message)`. Severities: `error`, `conflict`, `gap`, `warn`, `info`. Startumfang: acht Regeln (Konzept §6).
- **Views** (`src/lotse/views/*.sql`) sind benannte Abfragen; **Renderer** (live, archify, mermaid) teilen eine Schnittstelle: View-Abfrage rein, Darstellung raus.
- **Stufen** (auch Spaltenreihenfolge im Viewer): Entscheidung → Datenprodukt → Kennzahl → Dimension → Tabelle → Quelle. `lotse next` sortiert Befunde nach Stufe und Severity.
- **Live-Pfad:** Dateiwächter → inkrementeller Build → Knoten-/Kanten-Diff per SSE → Viewer ohne Neuladen. Ziel < 2 s vom Speichern bis zum Bild.

## Invarianten

- Kein Zustand, der nur in DuckDB, im Viewer oder im Chatverlauf existiert.
- Eine Datei pro Entität. `id` hat die Form `<typ>.<slug>` und ändert sich nie; Umbenennen ändert nur `name`.
- Sortierte Schlüssel, keine Zeitstempel im YAML-Inhalt (kleine, mergebare Diffs).
- Beziehungen sind ID-Listen (`serves`, `from_tables`, `from_sources`, `grain`); daraus entstehen die Kanten.
- Fachliche Angaben verweisen per `statement` auf ihre Herkunft.
- Konflikt = mehrere abweichende Einträge in `definitions`. Nie automatisch glätten; Einigung = auf einen Eintrag reduzieren + `status: agreed`.
- Validierung, Gap-Analyse, Generierung, Rendering sind deterministischer Code. Generatoren idempotent und byte-stabil.
- Kein Schreiben nach Fabric oder ADO ohne ausdrückliche Freigabe (`--apply`); Standard ist Dry-Run.
- Alles offline lauffähig: Tests ohne Netzwerkzugriff, Demo ohne Fabric/ADO/LLM.

## Tests

- Je Regel ein positives und ein negatives Fixture.
- Snapshot-Tests für Generatoren.
- Die Replay-Schritte in `demo/replay/steps/` sind zugleich der E2E-Test: nach jedem Schritt wird die erwartete Befundliste geprüft.

## Meilensteine

M1 Modell/Schema/`init`/`build`/`check`/Regeln → M2 `serve` + Live-Viewer → M3 Replay-Demo → M4 Generatoren (ODCS v3.1.0, TMDL, Mermaid, Archify) → M5 Claude-Code-Moderation → M6 ADO-Adapter. Demo vor Adaptern ist bewusst so gewählt. Abnahmekriterien: Konzept §11.

## Offene Entscheidungen (nicht eigenmächtig treffen, nachfragen)

- `gen ado` über Remote-MCP-Server oder REST?
- DPU_REQ-Excel als Import/Export?
- Archify-JSON-Schema zu Beginn von M4 gegen aktuelle Referenz prüfen.
- Siebter Entitätstyp `rule`, falls in echten Sessions > ⅓ der Aussagen im Freitext landet.

## Hinweis zu M5

Das Konzept (§9) sieht Moderator-Regeln für Claude Code vor (eine Frage pro Antwort, vorher `lotse next --json`, erst `statement`, dann Entität ändern, Commits `req(<stufe>): …`). Diese gelten für den Workshop-Betrieb, nicht für die Entwicklung, und werden in M5 ergänzt (Sektion hier oder `.claude/skills/`, `.claude/commands/`, Hook in `.claude/settings.json`).
