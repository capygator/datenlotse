---
description: lotse-Workshop starten (Workspace wählen, Viewer starten, Stufe 1 eröffnen)
argument-hint: "[workspace-name]"
---

Lade den Skill `moderation` und befolge ihn für den Rest der Session.

1. Workspace bestimmen: `$ARGUMENTS`, falls angegeben (`workspaces/$ARGUMENTS`). Sonst `ls workspaces/` zeigen und fragen. Existiert er nicht: `uv run lotse init "<Name>"` nach Rückfrage.
2. Viewer im Hintergrund starten: `uv run lotse serve -w <ws>` und die URL nennen (Standard http://127.0.0.1:8765).
3. `uv run lotse status -w <ws>` ausführen und den Stand in zwei Sätzen zusammenfassen.
4. Fragen, ob Commits je Frage gewünscht sind.
5. `uv run lotse next --json -w <ws>` und die erste Frage stellen. Ist der Workspace leer: mit der Entscheidung beginnen (Stufe 1) und zuerst die anwesenden Stakeholder erfassen.
