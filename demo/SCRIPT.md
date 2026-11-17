# Demo-Sprechtext: Nordwind Maschinenbau

Fünf Minuten, ein Befehl, kein Netz. Start: `uv run lotse demo --replay` (Leertaste = nächster Schritt) oder `--auto` für Selbstlauf. Der Viewer öffnet sich im Browser; Frage und Antwort jedes Schritts werden oben eingeblendet.

## Vorspann (Schritt 00, 20 Sekunden)

> „Das ist Nordwind, ein fiktiver Maschinenbauer. Vier Leute sitzen im Raum: Geschäftsführung, Vertrieb, Controlling, Fertigungsplanung. Wir wollen ein Cockpit für den Auftragsbestand. Rechts seht ihr den Graphen der Anforderungen – noch leer. Links läuft Claude Code als Moderator. Alles, was erfasst wird, landet als YAML-Datei in Git.“

## Akt 1 – Entscheidung (Schritt 01, 30 Sekunden)

> „Wir fangen nicht bei Kennzahlen an, sondern bei der Entscheidung. Die Geschäftsführung sagt: Jeden Monat legen wir das Schichtmodell fest. Das ist der erste Knoten. Alles, was später kommt, muss sich darauf zurückführen lassen.“

Zeigen: ein Knoten in der ersten Spalte.

## Akt 2 – Datenprodukt und Kennzahlen (Schritte 02–03, 60 Sekunden)

> „Das Datenprodukt ist das Cockpit, das Controlling steht für die Zahlen gerade. Dann sechs Kennzahlen. Der Graph wächst – und er wird gelb. Jede Kennzahl hat eine Definition und einen Owner, aber noch keine Granularität und keine Tabelle. Das Tool sagt uns genau, was fehlt. Der Moderator fragt nicht nach Gefühl, sondern nach dem wichtigsten offenen Befund.“

Zeigen: Befundliste in der Seitenleiste, Fortschrittsbalken der Stufe Kennzahl.

## Akt 3 – Konflikt (Schritt 04, 45 Sekunden)

> „Jetzt wird es interessant. Controlling definiert Auftragsbestand anders als der Vertrieb: abzüglich fakturierter Positionen. Das Tool glättet nichts. Beide Definitionen stehen nebeneinander, mit Herkunft – wer hat was wann gesagt. Der Knoten wird rot.“

Zeigen: Klick auf *Auftragsbestand*, beide Definitionen mit Aussage.

## Akt 4 – Realitätscheck (Schritte 05–06, 60 Sekunden)

> „Jetzt die Daten. ERP, MES, CRM. Die Kennzahlen hängen sich an Tabellen, die Tabellen an Quellen. Und eine Lücke bleibt: Liefertreue braucht den zugesagten Liefertermin – und den gibt es in keinem System. Er steht in E-Mails. Die Lücke ist sichtbar bis zur Quelle, mit offener Frage und Owner.“

Zeigen: *Fakt Lieferzusage* ohne Quelle, offene Frage beim Vertrieb.

## Akt 5 – Einigung (Schritt 07, 45 Sekunden)

> „Die Geschäftsführung entscheidet: Für die Kapazitätsplanung zählt, was noch nicht geliefert ist. `/lotse-decide` reduziert auf eine Definition und legt die Begründung als Aussage ab. Der Konflikt ist weg – und der Git-Diff zeigt genau diese Entscheidung.“

Zeigen: Knoten wird grün; optional `git diff` der Kennzahl.

## Akt 6 – Ergebnis (Schritt 08, 60 Sekunden)

> „Aus demselben Graphen entstehen die Artefakte: ein Data Contract nach ODCS, das semantische Modell als TMDL für Power BI, ein Backlog-Entwurf für Azure DevOps und ein Lineage-Bild. Alles deterministisch – gleicher Input, byte-gleicher Output. Und der Workshop selbst steht als Git-Historie da.“

Zeigen: `out/`-Ordner, Mermaid-Lineage.
