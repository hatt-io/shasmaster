CREATE TABLE page_font(page_id TEXT NOT NULL REFERENCES page(id),font_fingerprint TEXT NOT NULL,PRIMARY KEY(page_id,font_fingerprint));
CREATE INDEX font_pages ON page_font(font_fingerprint,page_id);
