---
description: Definitionskonflikt einer Kennzahl auflösen und Entscheidung dokumentieren
argument-hint: "<measure-id oder slug>"
---

Kennzahl: `$ARGUMENTS` (ohne Präfix → `measure.$ARGUMENTS`).

1. Datei `measures/<slug>.yaml` lesen und alle `definitions` nummeriert zeigen, mit `by` und Herkunft (Text der verlinkten Aussage).
2. Fragen: Welche Definition gilt, und wer entscheidet? Optional eine neu formulierte Definition. Nicht selbst wählen.
3. Die Entscheidung als neue Aussage ablegen (`statements/NNNN.yaml`, `by` = entscheidende Person, Begründung wörtlich).
4. `definitions` auf genau einen Eintrag reduzieren, `status: agreed`, `statement:` der Kennzahl auf die Entscheidungsaussage setzen.
5. `uv run lotse check` muss sauber sein; den Befund `measure_definition_conflict` gibt es danach nicht mehr.
6. In einem Satz zurückspiegeln. Commit vorschlagen: `req(measure): <Name> – Definition von <wem> festgelegt`.
