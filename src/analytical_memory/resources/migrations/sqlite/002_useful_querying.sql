ALTER TABLE node_attribute ADD COLUMN searchable INTEGER NOT NULL DEFAULT 0
    CHECK (searchable IN (0, 1));

ALTER TABLE evidence_binding RENAME TO evidence_binding_v1;
ALTER TABLE assertion RENAME TO assertion_v1;

CREATE TABLE relation (
    id TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL REFERENCES node(id),
    type TEXT NOT NULL,
    target_node_id TEXT NOT NULL REFERENCES node(id),
    logical_key TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (source_node_id, type, target_node_id, logical_key)
) STRICT;

CREATE TABLE assertion (
    id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('node_attribute', 'relation')),
    target_id TEXT NOT NULL,
    attribute_id TEXT REFERENCES node_attribute(id),
    relation_id TEXT REFERENCES relation(id),
    stance TEXT NOT NULL CHECK (stance IN ('supports', 'contradicts')),
    basis TEXT NOT NULL CHECK (basis IN ('observed', 'computed', 'inferred', 'declared')),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    review_status TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    recorded_at TEXT NOT NULL,
    method TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source(id),
    run_id TEXT NOT NULL REFERENCES analytical_run(id),
    supersedes_assertion_id TEXT REFERENCES assertion(id),
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('active', 'superseded', 'retracted')),
    stable_key TEXT NOT NULL UNIQUE,
    stable_key_version INTEGER NOT NULL CHECK (stable_key_version IN (1, 2)),
    CHECK (
        (target_kind = 'node_attribute' AND attribute_id = target_id AND relation_id IS NULL)
        OR
        (target_kind = 'relation' AND relation_id = target_id AND attribute_id IS NULL)
    )
) STRICT;

INSERT INTO assertion (
    id, target_kind, target_id, attribute_id, relation_id, stance, basis,
    confidence, review_status, valid_from, valid_to, recorded_at, method,
    source_id, run_id, supersedes_assertion_id, lifecycle, stable_key,
    stable_key_version
)
SELECT
    id, 'node_attribute', attribute_id, attribute_id, NULL, stance, basis,
    confidence, review_status, valid_from, valid_to, recorded_at, method,
    source_id, run_id, supersedes_assertion_id, lifecycle, stable_key, 1
FROM assertion_v1;

CREATE TABLE metric (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analytical_run(id),
    definition_version TEXT NOT NULL,
    value_json TEXT NOT NULL,
    unit TEXT,
    numerator REAL,
    denominator REAL,
    dimensions_json TEXT NOT NULL,
    dimensions_hash TEXT NOT NULL,
    method_version TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    complete INTEGER NOT NULL CHECK (complete IN (0, 1)),
    invalidated INTEGER NOT NULL CHECK (invalidated IN (0, 1)),
    recorded_at TEXT NOT NULL,
    UNIQUE (run_id, definition_version, dimensions_hash)
) STRICT;

CREATE TABLE evidence_binding (
    id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('assertion', 'metric')),
    target_id TEXT NOT NULL,
    assertion_id TEXT REFERENCES assertion(id),
    metric_id TEXT REFERENCES metric(id),
    fragment_id TEXT NOT NULL REFERENCES evidence_fragment(id),
    role TEXT NOT NULL CHECK (role IN ('supports', 'contradicts', 'contextualizes')),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    review_status TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (target_kind, target_id, fragment_id, role),
    CHECK (
        (target_kind = 'assertion' AND assertion_id = target_id AND metric_id IS NULL)
        OR
        (target_kind = 'metric' AND metric_id = target_id AND assertion_id IS NULL)
    )
) STRICT;

INSERT INTO evidence_binding (
    id, target_kind, target_id, assertion_id, metric_id, fragment_id, role,
    confidence, review_status, recorded_at
)
SELECT
    id, 'assertion', assertion_id, assertion_id, NULL, fragment_id, role,
    confidence, review_status, recorded_at
FROM evidence_binding_v1;

DROP TABLE evidence_binding_v1;
DROP TABLE assertion_v1;

CREATE TABLE search_document (
    id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind = 'node_attribute'),
    target_id TEXT NOT NULL REFERENCES node_attribute(id),
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    extraction_version TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('active', 'stale')),
    recorded_at TEXT NOT NULL,
    UNIQUE (target_kind, target_id, chunk_index, extraction_version)
) STRICT;

CREATE VIRTUAL TABLE search_document_fts USING fts5(
    document_id UNINDEXED,
    content,
    tokenize = 'unicode61'
);

CREATE TABLE schema_migration (
    backend_profile TEXT NOT NULL,
    version INTEGER NOT NULL,
    checksum TEXT NOT NULL,
    target_fingerprint TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    PRIMARY KEY (backend_profile, version)
) STRICT;

CREATE INDEX assertion_target_idx ON assertion(target_kind, target_id);
CREATE INDEX relation_source_idx ON relation(source_node_id, type);
CREATE INDEX relation_target_idx ON relation(target_node_id, type);
CREATE INDEX metric_current_idx ON metric(definition_version, dimensions_hash, complete, invalidated);
CREATE INDEX search_document_target_idx ON search_document(target_kind, target_id);

CREATE TRIGGER node_attribute_cardinality_consistency
BEFORE INSERT ON node_attribute
WHEN EXISTS (
    SELECT 1 FROM node_attribute AS existing
    WHERE existing.node_id = NEW.node_id
      AND existing.name = NEW.name
      AND existing.cardinality <> NEW.cardinality
)
BEGIN
    SELECT RAISE(ABORT, 'node attribute slot cardinality conflict');
END;

PRAGMA user_version = 2;
