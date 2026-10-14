-- The composite key already identifies each row; do not store a second copy
-- in an implicit rowid table plus its separate primary-key index.
CREATE TABLE page_font_compact(
    page_id TEXT NOT NULL REFERENCES page(id),
    font_fingerprint TEXT NOT NULL,
    PRIMARY KEY(page_id,font_fingerprint)
) WITHOUT ROWID;
INSERT INTO page_font_compact SELECT page_id,font_fingerprint FROM page_font;
DROP TABLE page_font;
ALTER TABLE page_font_compact RENAME TO page_font;
CREATE INDEX font_pages ON page_font(font_fingerprint,page_id);
