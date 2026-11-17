-- Kennzahl ohne Granularität.
SELECT 'missing_grain' AS rule, 'gap' AS severity, n.id AS node_id,
       'Kennzahl „' || n.name || '“ hat keine Granularität (grain fehlt)' AS message
FROM node n
WHERE n.type = 'measure'
  AND NOT EXISTS (SELECT 1 FROM edge e WHERE e.src = n.id AND e.kind = 'grain')
