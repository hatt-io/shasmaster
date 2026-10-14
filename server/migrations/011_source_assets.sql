CREATE TABLE page_source(
    page_id TEXT NOT NULL REFERENCES page(id),
    source_sha TEXT NOT NULL,
    asset_path TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(page_id,source_sha)
);
