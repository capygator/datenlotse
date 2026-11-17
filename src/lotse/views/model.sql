-- title: Datenmodell
-- kind: erd
-- description: Gold-Tabellen mit Spalten und Beziehungen aus columns[].references (Fremdschlüssel → Schlüsselspalte der Zieltabelle).
WITH
worst AS (
    SELECT f.node_id, arg_min(f.severity, s.rank) AS severity
    FROM finding f JOIN severity s ON s.name = f.severity
    WHERE f.node_id IS NOT NULL
    GROUP BY f.node_id
),
col AS (
    SELECT
        a.id AS table_id,
        a.value AS payload,
        CAST(json_extract(a.value, '$.pos') AS INTEGER) AS pos,
        json_extract_string(a.value, '$.name') AS name,
        coalesce(CAST(json_extract(a.value, '$.key') AS BOOLEAN), false) AS is_key,
        json_extract_string(a.value, '$.references') AS references_table
    FROM attr a
    WHERE a.key = 'column'
),
-- Zielspalte einer Referenz: die einzige Schlüsselspalte der Zieltabelle (sonst NULL).
target_key AS (
    SELECT table_id, CASE WHEN count(*) = 1 THEN any_value(name) END AS key_column
    FROM col WHERE is_key
    GROUP BY table_id
),
tbl AS (
    SELECT n.id, n.name, n.status, k.value AS kind
    FROM node n LEFT JOIN attr k ON k.id = n.id AND k.key = 'kind'
    WHERE n.type = 'table'
),
lanes(lane, lane_label, kind) AS (VALUES (0, 'Dimensionen', 'dimension'), (1, 'Fakten', 'fact'))
SELECT
    'node' AS element, t.id, t.name AS label, NULL AS sublabel, l.lane, l.lane_label, t.status,
    w.severity AS finding, NULL AS src, NULL AS dst,
    (SELECT to_json(list(c.payload::JSON ORDER BY c.pos)) FROM col c WHERE c.table_id = t.id)
        AS detail
FROM tbl t
JOIN lanes l ON l.kind = t.kind
LEFT JOIN worst w ON w.node_id = t.id
UNION ALL
SELECT
    'edge', NULL, c.name, NULL, NULL, NULL, NULL, NULL, c.table_id, c.references_table,
    to_json({'from_column': c.name, 'to_column': k.key_column})
FROM col c
JOIN node r ON r.id = c.references_table
LEFT JOIN target_key k ON k.table_id = c.references_table
WHERE c.references_table IS NOT NULL AND c.references_table <> c.table_id
ORDER BY element DESC, lane, id, src, dst, label
