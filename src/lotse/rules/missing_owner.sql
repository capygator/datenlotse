-- Kennzahl oder Datenprodukt ohne Owner.
SELECT 'missing_owner' AS rule, 'gap' AS severity, n.id AS node_id,
       CASE n.type WHEN 'measure' THEN 'Kennzahl' ELSE 'Datenprodukt' END
       || ' „' || n.name || '“ hat keinen Owner' AS message
FROM node n
WHERE n.type IN ('measure', 'product')
  AND NOT EXISTS (SELECT 1 FROM edge e WHERE e.src = n.id AND e.kind = 'owner')
