-- Mehr als eine inhaltlich abweichende Definition. Leerraum zählt nicht als Abweichung.
SELECT 'measure_definition_conflict' AS rule, 'conflict' AS severity, n.id AS node_id,
       'Kennzahl „' || n.name || '“ hat ' || count(DISTINCT norm) || ' abweichende Definitionen ('
       || string_agg(DISTINCT stakeholder_id, ', ' ORDER BY stakeholder_id) || ')' AS message
FROM node n
JOIN (
    SELECT measure_id, stakeholder_id, trim(regexp_replace(text, '\s+', ' ', 'g')) AS norm
    FROM definition
) d ON d.measure_id = n.id
GROUP BY n.id, n.name
HAVING count(DISTINCT norm) > 1
