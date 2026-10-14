CREATE TABLE jastrow_form_vector(
    cache_key TEXT PRIMARY KEY,
    spelling TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX jastrow_form_vector_model ON jastrow_form_vector(model_revision);
