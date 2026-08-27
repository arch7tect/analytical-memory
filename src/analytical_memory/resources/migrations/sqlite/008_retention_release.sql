ALTER TABLE evidence_acquisition ADD COLUMN released_at TEXT;
ALTER TABLE evidence_acquisition ADD COLUMN release_reason TEXT;

PRAGMA user_version = 8;
