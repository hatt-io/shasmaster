CREATE TABLE jastrow_source_form(
    id TEXT PRIMARY KEY,
    form TEXT NOT NULL,
    normalized TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    revision TEXT NOT NULL
);
CREATE INDEX jastrow_source_form_text ON jastrow_source_form(normalized);
