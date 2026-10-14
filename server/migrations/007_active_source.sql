ALTER TABLE page ADD COLUMN active_revision TEXT REFERENCES page_revision(id);
UPDATE page SET active_revision=(SELECT id FROM page_revision WHERE page_id=page.id AND source_sha=page.source_sha ORDER BY created_at DESC,rowid DESC LIMIT 1);
