CREATE TABLE saved_meaning (
    spelling TEXT COLLATE BINARY NOT NULL,
    text TEXT COLLATE BINARY NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('auto','ltr','rtl')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(spelling,text)
);
-- Seed existing handwritten annotations, not former dictionary passages.
INSERT OR IGNORE INTO saved_meaning(spelling,text,direction)
SELECT o.text,r.text,r.direction FROM annotation a
JOIN occurrence o ON o.id=a.occurrence_id
JOIN annotation_revision r ON r.occurrence_id=a.occurrence_id AND r.revision=a.head_revision
WHERE r.deleted=0 AND r.conflict=0 AND length(trim(r.text))>0
AND NOT EXISTS (
    SELECT 1 FROM json_each(coalesce(r.components_json,'[]')) c
    WHERE json_extract(c.value,'$.entry_id') IS NOT NULL
       OR json_extract(c.value,'$.source.record') IS NOT NULL
);
