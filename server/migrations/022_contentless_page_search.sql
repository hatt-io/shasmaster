-- Keep search positions, but not a second copy of the retained page text.
ALTER TABLE retained_page_text RENAME TO retained_page_text_with_content;
CREATE TABLE retained_page_search_id(
    id INTEGER PRIMARY KEY,
    page_id TEXT NOT NULL UNIQUE REFERENCES page(id)
);
INSERT INTO retained_page_search_id(id,page_id)
    SELECT rowid,page_id FROM retained_page_text_with_content;
CREATE VIRTUAL TABLE retained_page_text USING fts5(
    page_id UNINDEXED, text, normalized, content='', contentless_delete=1,
    tokenize='unicode61 remove_diacritics 2'
);
INSERT INTO retained_page_text(rowid,page_id,text,normalized)
    SELECT rowid,page_id,text,normalized FROM retained_page_text_with_content;
DROP TABLE retained_page_text_with_content;
