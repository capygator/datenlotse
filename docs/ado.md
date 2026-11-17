# `lotse gen ado` – Backlog nach Azure DevOps

Transport: **REST** (Work Items API 7.1), vorläufig entschieden, Bestätigung offen. Der Transport
steckt hinter `WorkItemStore` (`src/lotse/gen/ado/sync.py`); ein MCP-Weg würde nur dieses
Protokoll neu implementieren, Planung (`plan.py`) und Abgleich (`sync.py`) bleiben.

## Backlog-Struktur

| Ebene | Agile | Scrum | Woraus | Parent |
|---|---|---|---|---|
| epic | Epic | Epic | je `product.*` | – |
| feature | Feature | Feature | je `measure.*` | erstes Datenprodukt (nach id), das die Kennzahl führt |
| feature | Feature | Feature | je `table.*` inkl. Quellanbindung als Akzeptanzkriterien | erstes Datenprodukt, das die Tabelle über Kennzahlen/Dimensionen nutzt |
| story | User Story | Product Backlog Item | je Befund `conflict`/`gap`/`warn` (`info` nicht) | Item des Knotens; Dimension → erste Kennzahl, Quelle → erste Tabelle, Entscheidung → erstes Produkt |
| story | User Story | Product Backlog Item | je offener `question.*` | erstes auflösbares `about` |

Quellen und Entscheidungen werden nicht eigene Items, sondern stehen in Beschreibung und
Akzeptanzkriterien. Akzeptanzkriterien gehen bei Stories in
`Microsoft.VSTS.Common.AcceptanceCriteria`, bei Epic/Feature als Abschnitt in `System.Description`.

## Dry-Run (Standard, offline)

```bash
uv run lotse gen ado -w demo/nordwind [--process agile|scrum]
```

Schreibt `<ws>/out/ado/backlog.json` (byte-stabil, ohne Org/Projekt/Zeitstempel) und zeigt die
Hierarchie. Bricht ab, wenn der Workspace `error`-Befunde hat.

## Schreiben (`--apply`)

```bash
export AZURE_DEVOPS_EXT_PAT=…        # oder LOTSE_ADO_PAT; Scope: Work Items (Read & write)
uv run lotse gen ado -w demo/nordwind --apply \
  --org <organisation> --project "<Testprojekt>" --process agile \
  [--area "<Projekt>\\<Area>"] [--iteration "<Projekt>\\<Sprint>"] [--scope nordwind]
```

`--org` und `--project` müssen explizit angegeben werden (keine Umgebungsvariablen, keine
Standardwerte). Area/Iteration werden nur beim Anlegen gesetzt.

**Idempotenz:** Jedes Item trägt `lotse`, `lotse-ws:<scope>` (Standard: Ordnername des Workspaces;
Umbenennen des Ordners oder anderer `--scope` erzeugt einen zweiten, getrennten Satz Items)
und `lotse:<key>` (lotse-id bzw. `finding:<regel>:<knoten>`). Vor dem Schreiben lädt lotse per WIQL
alle Items mit dem Scope-Tag und ordnet sie per exaktem Tag-Vergleich zu.

- vorhanden → nur abweichende Felder (Titel, Beschreibung, Akzeptanzkriterien) werden
  überschrieben; fremde Tags bleiben, `System.State` wird nie geändert; Handänderungen an
  diesen Feldern in ADO überschreibt der nächste Lauf (YAML ist die Wahrheit)
- Parent-Link nur, wenn das Item noch keinen hat; abweichender Parent → Warnung, kein Umhängen
- mehrere Items mit gleichem Schlüssel → kleinste ID gewinnt, Warnung
- nicht mehr geplante Items (z. B. gelöste Lücke, beantwortete Frage) → als „veraltet“
  gemeldet, nicht geschlossen oder gelöscht
- Vorab-Check der Work-Item-Typen: falscher `--process` bricht ohne Schreibzugriff ab

## Abnahme M6 im Testprojekt (manuell, nicht automatisiert)

1. Leeres ADO-Testprojekt (Agile oder Scrum) anlegen, PAT mit Scope *Work Items (Read & write)*.
2. Dry-Run ansehen: `uv run lotse gen ado -w demo/nordwind --process <agile|scrum>`.
3. Erster Lauf mit `--apply` (siehe oben): Ausgabe `18 angelegt`. In Boards → Backlogs (Epics)
   prüfen: 1 Epic, darunter 15 Features, Story „Frage klären …“ unter *Kennzahl: Liefertreue*,
   Story „Quelle für „Fakt Lieferzusage“ klären“ unter *Tabelle: Fakt Lieferzusage*.
4. Zweiter Lauf, identischer Befehl: `0 angelegt, 0 geändert, 0 verknüpft, 18 unverändert`.
   Falls ADO HTML in Beschreibungen normalisiert, kann hier „geändert“ statt „unverändert“
   stehen – das wäre zu melden; Duplikate entstehen in keinem Fall.
5. Optional: in einer Kopie des Workspaces einen Namen ändern und erneut laufen lassen → nur
   die betroffenen Items werden geändert.

Zu prüfende API-Annahmen (aus Dokumentation, nicht gegen echtes ADO getestet):
`POST …/_apis/wit/wiql`, `GET …/_apis/wit/workitems?ids=…&$expand=relations`,
`POST …/_apis/wit/workitems/$<Typ>` und `PATCH …/_apis/wit/workitems/<id>` mit
`application/json-patch+json`, Parent-Link `System.LinkTypes.Hierarchy-Reverse` auf
`https://dev.azure.com/<org>/_apis/wit/workItems/<id>`, WIQL `[System.Tags] CONTAINS '<tag>'`,
`GET …/_apis/wit/workitemtypes`, Basic-Auth mit `:<PAT>`.
