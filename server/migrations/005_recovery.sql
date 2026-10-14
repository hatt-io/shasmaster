CREATE TABLE recovery_item(id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload_json TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', resolution_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX recovery_pending ON recovery_item(status,created_at);
