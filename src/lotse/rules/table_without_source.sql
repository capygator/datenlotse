-- Tabelle hat keine Quelle.
SELECT 'table_without_source' AS rule, 'gap' AS severity, n.id AS node_id,
       'Tabelle „' || n.name || '“ hat keine Quelle (from_sources fehlt)' AS message
FROM node n
WHERE n.type = 'table'
  AND NOT EXISTS (SELECT 1 FROM edge e WHERE e.src = n.id AND e.kind = 'from_sources')
