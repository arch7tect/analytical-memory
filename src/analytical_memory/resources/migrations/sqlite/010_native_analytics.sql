CREATE TABLE memory_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation TEXT NOT NULL,
    data_revision INTEGER NOT NULL CHECK (data_revision >= 0)
) STRICT;
CREATE TABLE analysis_observation (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analytical_run(id),
    identity_hash TEXT NOT NULL UNIQUE,
    generation TEXT NOT NULL,
    data_revision INTEGER NOT NULL,
    population_hash TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    manifest_object_id TEXT NOT NULL REFERENCES evidence_object(id),
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    recorded_at TEXT NOT NULL
) STRICT;
ALTER TABLE metric ADD COLUMN origin TEXT NOT NULL DEFAULT 'caller'
    CHECK (origin IN ('caller', 'native'));

PRAGMA user_version = 10;
