---
description: Zusammenfassung der Session plus Commit-Vorschlag
---

1. `git status --short` und `git diff --stat` für den aktiven Workspace; neue Aussagen (`statements/`) dieser Session lesen.
2. Zusammenfassen, gegliedert nach Stufe: Was wurde erfasst, welche Konflikte sind offen, welche Fragen offen (mit Owner).
3. `uv run lotse status` anhängen.
4. Commit-Vorschlag im Format `req(<stufe>): <fachliche Änderung>` (ein Commit je abgeschlossener Frage, falls noch nicht committet). Nur committen, wenn der Mensch zustimmt. Keine Attribution-Zeilen.
