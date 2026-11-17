-- Kennzahl stützt keine Entscheidung.
SELECT 'measure_without_decision' AS rule, 'warn' AS severity, n.id AS node_id,
       'Kennzahl „' || n.name || '“ stützt keine Entscheidung (serves fehlt)' AS message
FROM node n
WHERE n.type = 'measure'
  AND NOT EXISTS (SELECT 1 FROM edge e WHERE e.src = n.id AND e.kind = 'serves')
