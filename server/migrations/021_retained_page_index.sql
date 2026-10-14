CREATE VIRTUAL TABLE retained_page_text USING fts5(
    page_id UNINDEXED, text, normalized, tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE retained_page_cache(
    page_id TEXT PRIMARY KEY REFERENCES page(id),
    accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
