CREATE TABLE namespace_declaration (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source(id),
    fragment_id TEXT REFERENCES evidence_fragment(id),
    recorded_at TEXT NOT NULL
) STRICT;

ALTER TABLE entity_declaration ADD COLUMN description TEXT;
ALTER TABLE observed_field ADD COLUMN description TEXT;
ALTER TABLE ontology_declaration ADD COLUMN description TEXT;

PRAGMA user_version = 9;
