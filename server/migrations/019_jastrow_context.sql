CREATE TABLE jastrow_context_score(
    cache_key TEXT PRIMARY KEY,
    dictionary_revision TEXT NOT NULL,
    context_revision TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    software_revision TEXT NOT NULL,
    sense_id TEXT NOT NULL,
    input_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX jastrow_context_source ON jastrow_context_score(dictionary_revision,model_revision,software_revision);
