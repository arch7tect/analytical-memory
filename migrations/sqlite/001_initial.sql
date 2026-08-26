PRAGMA foreign_keys = ON;

CREATE TABLE ingestion_batch (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    input_hash TEXT NOT NULL,
    schema_fingerprint TEXT NOT NULL,
    result_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
) STRICT;

CREATE TABLE source (
    id TEXT PRIMARY KEY,
    natural_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    recorded_at TEXT NOT NULL
) STRICT;

CREATE TABLE analytical_run (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    batch_id TEXT NOT NULL UNIQUE REFERENCES ingestion_batch(id),
    source_id TEXT NOT NULL REFERENCES source(id),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    method TEXT NOT NULL,
    recorded_at TEXT NOT NULL
) STRICT;

CREATE TABLE node (
    id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    type TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    display_label TEXT,
    privacy_class TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (namespace, type, natural_key)
) STRICT;

CREATE TABLE node_attribute (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL REFERENCES node(id),
    name TEXT NOT NULL,
    cardinality TEXT NOT NULL CHECK (cardinality IN ('single', 'multi')),
    value_json TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (node_id, name, value_hash)
) STRICT;

CREATE TABLE assertion (
    id TEXT PRIMARY KEY,
    attribute_id TEXT NOT NULL REFERENCES node_attribute(id),
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
    stable_key TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE evidence_object (
    id TEXT PRIMARY KEY,
    digest TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    media_type TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    recorded_at TEXT NOT NULL
) STRICT;

CREATE TABLE evidence_fragment (
    id TEXT PRIMARY KEY,
    evidence_object_id TEXT NOT NULL REFERENCES evidence_object(id),
    locator_kind TEXT NOT NULL CHECK (locator_kind = 'whole_object'),
    locator_json TEXT NOT NULL,
    extractor_id TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    digest TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (evidence_object_id, locator_kind, locator_json, extractor_id, extractor_version)
) STRICT;

CREATE TABLE evidence_binding (
    id TEXT PRIMARY KEY,
    assertion_id TEXT NOT NULL REFERENCES assertion(id),
    fragment_id TEXT NOT NULL REFERENCES evidence_fragment(id),
    role TEXT NOT NULL CHECK (role IN ('supports', 'contradicts', 'contextualizes')),
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    review_status TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (assertion_id, fragment_id, role)
) STRICT;

PRAGMA user_version = 1;
