DROP TABLE IF EXISTS embedding_record;
DROP TABLE IF EXISTS embedding_profile;
DROP TABLE IF EXISTS search_document_fts;
DROP TABLE IF EXISTS search_document;
DROP TABLE IF EXISTS evidence_binding;
DROP TABLE IF EXISTS assertion;
DROP TABLE IF EXISTS relation;
DROP TABLE IF EXISTS node_attribute;
DROP TABLE IF EXISTS node;
DROP TABLE IF EXISTS metric;
DROP TABLE IF EXISTS evidence_acquisition;
DROP TABLE IF EXISTS analytical_run;
DROP TABLE IF EXISTS ingestion_batch;

CREATE TABLE ingestion_batch (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('jsonl-import', 'join-materialization')),
    input_hash TEXT NOT NULL,
    schema_fingerprint TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
) STRICT;

CREATE TABLE analytical_run (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    batch_id TEXT REFERENCES ingestion_batch(id),
    source_id TEXT NOT NULL REFERENCES source(id),
    method TEXT NOT NULL,
    recorded_at TEXT NOT NULL
) STRICT;

CREATE TABLE evidence_acquisition (
    id TEXT PRIMARY KEY,
    evidence_object_id TEXT NOT NULL REFERENCES evidence_object(id),
    source_id TEXT NOT NULL REFERENCES source(id),
    run_id TEXT NOT NULL REFERENCES analytical_run(id),
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    retention_required INTEGER NOT NULL CHECK (retention_required IN (0, 1)),
    retain_until TEXT,
    method TEXT NOT NULL,
    review_status TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (evidence_object_id, run_id)
) STRICT;

CREATE TABLE node (
    id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    type TEXT NOT NULL,
    display_label TEXT,
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    recorded_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE INDEX node_type_idx ON node(namespace, type);

CREATE TABLE node_attribute (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL REFERENCES node(id) ON DELETE CASCADE,
    attribute_name TEXT NOT NULL,
    value_json TEXT NOT NULL,
    json_type TEXT NOT NULL CHECK (
        json_type IN ('unresolved', 'string', 'number', 'boolean', 'object', 'array')
    ),
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    searchable INTEGER NOT NULL DEFAULT 0 CHECK (searchable IN (0, 1)),
    source_id TEXT NOT NULL REFERENCES source(id),
    batch_id TEXT REFERENCES ingestion_batch(id),
    run_id TEXT REFERENCES analytical_run(id),
    fragment_id TEXT REFERENCES evidence_fragment(id),
    updated_at TEXT NOT NULL,
    UNIQUE (node_id, attribute_name)
) STRICT;

CREATE INDEX node_attribute_lookup_idx
    ON node_attribute(attribute_name, json_type, value_json);

CREATE TABLE relation (
    id TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL REFERENCES node(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    target_node_id TEXT NOT NULL REFERENCES node(id) ON DELETE CASCADE,
    logical_key TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    source_id TEXT NOT NULL REFERENCES source(id),
    batch_id TEXT REFERENCES ingestion_batch(id),
    run_id TEXT REFERENCES analytical_run(id),
    fragment_id TEXT REFERENCES evidence_fragment(id),
    updated_at TEXT NOT NULL,
    UNIQUE (source_node_id, type, target_node_id, logical_key)
) STRICT;

CREATE INDEX relation_source_idx ON relation(source_node_id, type, active);
CREATE INDEX relation_target_idx ON relation(target_node_id, type, active);

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
    fragment_id TEXT REFERENCES evidence_fragment(id),
    recorded_at TEXT NOT NULL,
    UNIQUE (run_id, definition_version, dimensions_hash)
) STRICT;

CREATE INDEX metric_current_idx
    ON metric(definition_version, dimensions_hash, complete, invalidated);

CREATE TABLE entity_declaration (
    entity_type TEXT PRIMARY KEY,
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    fields_json TEXT NOT NULL,
    declaration_hash TEXT NOT NULL,
    source_id TEXT REFERENCES source(id),
    fragment_id TEXT REFERENCES evidence_fragment(id),
    recorded_at TEXT NOT NULL
) STRICT;

CREATE TABLE observed_field (
    entity_type TEXT NOT NULL,
    field_name TEXT NOT NULL,
    json_type TEXT NOT NULL CHECK (
        json_type IN ('unresolved', 'string', 'number', 'boolean', 'object', 'array')
    ),
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    required INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0, 1)),
    nullable INTEGER NOT NULL DEFAULT 1 CHECK (nullable IN (0, 1)),
    searchable INTEGER NOT NULL DEFAULT 0 CHECK (searchable IN (0, 1)),
    declared INTEGER NOT NULL DEFAULT 0 CHECK (declared IN (0, 1)),
    first_batch_id TEXT REFERENCES ingestion_batch(id),
    last_batch_id TEXT REFERENCES ingestion_batch(id),
    PRIMARY KEY (entity_type, field_name)
) STRICT;

CREATE TABLE ontology_declaration (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind = 'join'),
    relation_type TEXT NOT NULL,
    from_entity TEXT NOT NULL,
    from_fields_json TEXT NOT NULL,
    to_entity TEXT NOT NULL,
    to_fields_json TEXT NOT NULL,
    definition_hash TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    source_id TEXT NOT NULL REFERENCES source(id),
    fragment_id TEXT REFERENCES evidence_fragment(id),
    recorded_at TEXT NOT NULL
) STRICT;

CREATE TABLE search_document (
    id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind = 'node_attribute'),
    target_id TEXT NOT NULL REFERENCES node_attribute(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    extraction_version TEXT NOT NULL,
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('active', 'stale')),
    recorded_at TEXT NOT NULL,
    UNIQUE (target_kind, target_id, chunk_index, extraction_version)
) STRICT;

CREATE VIRTUAL TABLE search_document_fts USING fts5(
    document_id UNINDEXED,
    content,
    tokenize = 'unicode61'
);

CREATE TABLE embedding_profile (
    id TEXT PRIMARY KEY,
    attribute_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    preprocessing_version TEXT NOT NULL,
    similarity TEXT NOT NULL CHECK (similarity = 'cosine'),
    privacy_ceiling TEXT NOT NULL CHECK (privacy_ceiling = 'public'),
    contract_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'building', 'ready', 'degraded')
    ),
    last_error TEXT,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE embedding_record (
    id TEXT PRIMARY KEY,
    search_document_id TEXT NOT NULL REFERENCES search_document(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES embedding_profile(id),
    input_content_hash TEXT NOT NULL,
    vector_blob BLOB NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    response_model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (search_document_id, profile_id, input_content_hash)
) STRICT;

CREATE INDEX embedding_record_profile_idx
    ON embedding_record(profile_id, search_document_id);

PRAGMA user_version = 5;
