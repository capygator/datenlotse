-- Kennzahl hat keine Gold-Tabelle.
SELECT 'measure_without_table' AS rule, 'gap' AS severity, n.id AS node_id,
       'Kennzahl „' || n.name || '“ hat keine Gold-Tabelle (from_tables fehlt)' AS message
FROM node n
WHERE n.type = 'measure'
  AND NOT EXISTS (SELECT 1 FROM edge e WHERE e.src = n.id AND e.kind = 'from_tables')
