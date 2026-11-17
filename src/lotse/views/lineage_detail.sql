-- title: Lineage (Detail)
-- kind: flow
-- description: Datenfluss Quelle → Tabelle → Kennzahl → Datenprodukt → Entscheidung, jede Kennzahl als eigener Knoten.
WITH
worst AS (
    SELECT f.node_id, arg_min(f.severity, s.rank) AS severity
    FROM finding f JOIN severity s ON s.name = f.severity
    WHERE f.node_id IS NOT NULL
    GROUP BY f.node_id
),
-- Zuordnung Kennzahl → Knoten (hier: jede Kennzahl einzeln).
grp AS (
    SELECT m.id AS measure_id, m.id AS group_id, m.name AS group_label
    FROM node m
    WHERE m.type = 'measure'
),
grp_node AS (
    SELECT
        m.id, m.name AS label, NULL AS sublabel, m.status, w.severity AS finding,
        NULL AS detail
    FROM node m
    LEFT JOIN worst w ON w.node_id = m.id
    WHERE m.type = 'measure'
),
lin_table AS (
    SELECT DISTINCT e.dst AS id
    FROM edge e JOIN node t ON t.id = e.dst AND t.type = 'table'
    WHERE e.kind = 'from_tables' AND e.src IN (SELECT measure_id FROM grp)
),
lin_source AS (
    SELECT DISTINCT e.dst AS id
    FROM edge e JOIN node s ON s.id = e.dst AND s.type = 'source'
    WHERE e.kind = 'from_sources' AND e.src IN (SELECT id FROM lin_table)
),
plain_node AS (
    SELECT n.id, n.name AS label, NULL AS sublabel,
        CASE n.type WHEN 'source' THEN 0 WHEN 'table' THEN 1 WHEN 'product' THEN 3 ELSE 4 END
            AS lane,
        n.status, w.severity AS finding, NULL AS detail
    FROM node n LEFT JOIN worst w ON w.node_id = n.id
    WHERE n.id IN (SELECT id FROM lin_table)
       OR n.id IN (SELECT id FROM lin_source)
       OR n.type IN ('product', 'decision')
),
lanes(lane, lane_label) AS (
    VALUES (0, 'Quelle'), (1, 'Tabelle'), (2, 'Kennzahl'), (3, 'Datenprodukt'), (4, 'Entscheidung')
),
nodes AS (
    SELECT id, label, sublabel, lane, status, finding, detail FROM plain_node
    UNION ALL
    SELECT id, label, sublabel, 2 AS lane, status, finding, detail FROM grp_node
),
edges AS (
    SELECT DISTINCT e.dst AS src, e.src AS dst, 'liefert' AS label
    FROM edge e
    WHERE e.kind = 'from_sources' AND e.src IN (SELECT id FROM lin_table)
      AND e.dst IN (SELECT id FROM lin_source)
    UNION
    SELECT DISTINCT e.dst, g.group_id, 'speist'
    FROM edge e JOIN grp g ON g.measure_id = e.src
    WHERE e.kind = 'from_tables' AND e.dst IN (SELECT id FROM lin_table)
    UNION
    SELECT DISTINCT g.group_id, e.src, 'Kennzahlen'
    FROM edge e JOIN grp g ON g.measure_id = e.dst
    JOIN node p ON p.id = e.src AND p.type = 'product'
    WHERE e.kind = 'measures'
    UNION
    SELECT DISTINCT e.src, e.dst, 'stützt'
    FROM edge e
    JOIN node p ON p.id = e.src AND p.type = 'product'
    JOIN node d ON d.id = e.dst AND d.type = 'decision'
    WHERE e.kind = 'serves'
)
SELECT 'node' AS element, n.id, n.label, n.sublabel, n.lane, l.lane_label, n.status, n.finding,
    NULL AS src, NULL AS dst, n.detail
FROM nodes n JOIN lanes l ON l.lane = n.lane
UNION ALL
SELECT 'edge', NULL, e.label, NULL, NULL, NULL, NULL, NULL, e.src, e.dst, NULL
FROM edges e
ORDER BY element DESC, lane, id, src, dst
