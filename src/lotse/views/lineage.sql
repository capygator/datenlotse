-- title: Lineage
-- kind: flow
-- description: Datenfluss Quelle → Tabelle → Kennzahlen → Datenprodukt → Entscheidung. Kennzahlen sind je Owner zu einem Block zusammengefasst, damit das Bild bei rund 8 bis 12 Kernknoten bleibt.
WITH
worst AS (
    SELECT f.node_id, arg_min(f.severity, s.rank) AS severity
    FROM finding f JOIN severity s ON s.name = f.severity
    WHERE f.node_id IS NOT NULL
    GROUP BY f.node_id
),
status_rank(status, rank) AS (VALUES ('conflict', 0), ('draft', 1), ('agreed', 2)),
-- Zuordnung Kennzahl → Block (hier: Owner der Kennzahl).
grp AS (
    SELECT
        m.id AS measure_id,
        'block.' || coalesce(split_part(o.dst, '.', 2), 'ohne-owner') AS group_id,
        coalesce(s.name, 'ohne Owner') AS group_label
    FROM node m
    LEFT JOIN edge o ON o.src = m.id AND o.kind = 'owner'
    LEFT JOIN node s ON s.id = o.dst
    WHERE m.type = 'measure'
),
grp_node AS (
    SELECT
        g.group_id AS id,
        any_value(g.group_label) AS label,
        string_agg(m.name, ', ' ORDER BY m.name) AS sublabel,
        arg_min(m.status, coalesce(sr.rank, 9)) AS status,
        arg_min(w.severity, coalesce(sv.rank, 99)) AS finding,
        to_json(list(m.id ORDER BY m.id)) AS detail
    FROM grp g
    JOIN node m ON m.id = g.measure_id
    LEFT JOIN status_rank sr ON sr.status = m.status
    LEFT JOIN worst w ON w.node_id = m.id
    LEFT JOIN severity sv ON sv.name = w.severity
    GROUP BY g.group_id
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
