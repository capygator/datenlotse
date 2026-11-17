-- Dimension wird von keiner Kennzahl als Granularität genutzt.
SELECT 'dimension_unused' AS rule, 'info' AS severity, n.id AS node_id,
       'Dimension „' || n.name || '“ wird von keiner Kennzahl genutzt' AS message
FROM node n
WHERE n.type = 'dimension'
  AND NOT EXISTS (SELECT 1 FROM edge e WHERE e.dst = n.id AND e.kind = 'grain')
