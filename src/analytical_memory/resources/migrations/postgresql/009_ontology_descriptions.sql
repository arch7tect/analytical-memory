CREATE TABLE namespace_declaration (
    name TEXT COLLATE "C" PRIMARY KEY,
    description TEXT NOT NULL,
    source_id TEXT COLLATE "C" NOT NULL REFERENCES source(id) DEFERRABLE INITIALLY IMMEDIATE,
    fragment_id TEXT COLLATE "C" REFERENCES evidence_fragment(id) DEFERRABLE INITIALLY IMMEDIATE,
    recorded_at TEXT COLLATE "C" NOT NULL
);

ALTER TABLE entity_declaration ADD COLUMN description TEXT;
ALTER TABLE observed_field ADD COLUMN description TEXT;
ALTER TABLE ontology_declaration ADD COLUMN description TEXT;
