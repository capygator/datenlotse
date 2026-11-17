-- ID-Verweis zeigt ins Leere.
SELECT 'dangling_reference' AS rule, 'error' AS severity, e.src AS node_id,
       'Verweis ' || e.kind || ' → ' || e.dst || ' zeigt ins Leere' AS message
FROM edge e
WHERE NOT EXISTS (SELECT 1 FROM node n WHERE n.id = e.dst)
