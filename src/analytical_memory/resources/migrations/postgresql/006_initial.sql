CREATE TABLE source (
    id TEXT COLLATE "C" PRIMARY KEY,
    natural_key TEXT COLLATE "C" NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    recorded_at TEXT COLLATE "C" NOT NULL
);

CREATE TABLE evidence_object (
    id TEXT COLLATE "C" PRIMARY KEY,
    digest TEXT COLLATE "C" NOT NULL UNIQUE,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    media_type TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    recorded_at TEXT COLLATE "C" NOT NULL
);

CREATE TABLE schema_migration (
    backend_profile TEXT NOT NULL,
    version INTEGER NOT NULL,
    checksum TEXT COLLATE "C" NOT NULL,
    target_fingerprint TEXT COLLATE "C" NOT NULL,
    applied_at TEXT COLLATE "C" NOT NULL,
    tool_version TEXT NOT NULL,
    PRIMARY KEY (backend_profile, version)
);

CREATE TABLE evidence_derivation (
    id TEXT COLLATE "C" PRIMARY KEY,
    input_object_id TEXT COLLATE "C" NOT NULL REFERENCES evidence_object(id) DEFERRABLE INITIALLY IMMEDIATE,
    output_object_id TEXT COLLATE "C" NOT NULL REFERENCES evidence_object(id) DEFERRABLE INITIALLY IMMEDIATE,
    method TEXT NOT NULL,
    method_version TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    recorded_at TEXT COLLATE "C" NOT NULL,
    UNIQUE (input_object_id, output_object_id, method, method_version, parameters_json)
);

CREATE TABLE evidence_location (
    id TEXT COLLATE "C" PRIMARY KEY,
    evidence_object_id TEXT COLLATE "C" NOT NULL REFERENCES evidence_object(id) DEFERRABLE INITIALLY IMMEDIATE,
    provider TEXT COLLATE "C" NOT NULL,
    root_id TEXT COLLATE "C" NOT NULL,
    object_key TEXT COLLATE "C" NOT NULL,
    availability TEXT NOT NULL CHECK (availability IN ('present', 'missing')),
    verified_at TEXT COLLATE "C",
    recorded_at TEXT COLLATE "C" NOT NULL,
    UNIQUE (evidence_object_id, provider, root_id, object_key)
);

CREATE TABLE evidence_verification (
    id TEXT COLLATE "C" PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('object', 'fragment', 'snapshot', 'import')),
    target_id TEXT COLLATE "C" NOT NULL,
    digest TEXT COLLATE "C" NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('verified', 'corrupt', 'missing')),
    byte_size BIGINT CHECK (byte_size IS NULL OR byte_size >= 0),
    method TEXT NOT NULL,
    checked_at TEXT COLLATE "C" NOT NULL,
    UNIQUE (target_kind, target_id, checked_at, method)
);

CREATE TABLE evidence_retirement (
    evidence_object_id TEXT COLLATE "C" PRIMARY KEY REFERENCES evidence_object(id) DEFERRABLE INITIALLY IMMEDIATE,
    digest TEXT COLLATE "C" NOT NULL UNIQUE,
    plan_id TEXT COLLATE "C" NOT NULL,
    reason TEXT NOT NULL,
    retired_at TEXT COLLATE "C" NOT NULL
);

CREATE TABLE evidence_fragment (
    id TEXT COLLATE "C" PRIMARY KEY,
    evidence_object_id TEXT COLLATE "C" NOT NULL REFERENCES evidence_object(id) DEFERRABLE INITIALLY IMMEDIATE,
    locator_kind TEXT NOT NULL CHECK (locator_kind IN ('whole_object', 'structured', 'record_key', 'byte_range', 'line_range', 'time_interval', 'sample_interval')),
    locator_json TEXT NOT NULL,
    extractor_id TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    digest TEXT COLLATE "C" NOT NULL,
    privacy_class TEXT NOT NULL,
    recorded_at TEXT COLLATE "C" NOT NULL,
    UNIQUE (evidence_object_id, locator_kind, locator_json, extractor_id, extractor_version)
);

CREATE INDEX evidence_location_object_idx ON evidence_location(evidence_object_id);
CREATE INDEX evidence_verification_target_idx ON evidence_verification(target_kind, target_id, checked_at);

CREATE TABLE ingestion_batch (
    id TEXT COLLATE "C" PRIMARY KEY,
    idempotency_key TEXT COLLATE "C" NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('jsonl-import', 'join-materialization')),
    input_hash TEXT COLLATE "C" NOT NULL,
    schema_fingerprint TEXT COLLATE "C" NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    recorded_at TEXT COLLATE "C" NOT NULL
);

CREATE TABLE analytical_run (
    id TEXT COLLATE "C" PRIMARY KEY,
    idempotency_key TEXT COLLATE "C" NOT NULL UNIQUE,
    batch_id TEXT COLLATE "C" REFERENCES ingestion_batch(id) DEFERRABLE INITIALLY IMMEDIATE,
    source_id TEXT COLLATE "C" NOT NULL REFERENCES source(id) DEFERRABLE INITIALLY IMMEDIATE,
    method TEXT NOT NULL,
    recorded_at TEXT COLLATE "C" NOT NULL
);

CREATE TABLE evidence_acquisition (
    id TEXT COLLATE "C" PRIMARY KEY,
    evidence_object_id TEXT COLLATE "C" NOT NULL REFERENCES evidence_object(id) DEFERRABLE INITIALLY IMMEDIATE,
    source_id TEXT COLLATE "C" NOT NULL REFERENCES source(id) DEFERRABLE INITIALLY IMMEDIATE,
    run_id TEXT COLLATE "C" NOT NULL REFERENCES analytical_run(id) DEFERRABLE INITIALLY IMMEDIATE,
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    retention_required INTEGER NOT NULL CHECK (retention_required IN (0, 1)),
    retain_until TEXT COLLATE "C",
    method TEXT NOT NULL,
    review_status TEXT NOT NULL,
    recorded_at TEXT COLLATE "C" NOT NULL,
    UNIQUE (evidence_object_id, run_id)
);

CREATE TABLE node (
    id TEXT COLLATE "C" PRIMARY KEY,
    namespace TEXT COLLATE "C" NOT NULL,
    type TEXT COLLATE "C" NOT NULL,
    display_label TEXT,
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    recorded_at TEXT COLLATE "C" NOT NULL,
    updated_at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX node_type_idx ON node(namespace, type);

CREATE TABLE node_attribute (
    id TEXT COLLATE "C" PRIMARY KEY,
    node_id TEXT COLLATE "C" NOT NULL REFERENCES node(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    attribute_name TEXT COLLATE "C" NOT NULL,
    value_json TEXT COLLATE "C" NOT NULL,
    json_type TEXT NOT NULL CHECK (json_type IN ('unresolved', 'string', 'number', 'boolean', 'object', 'array')),
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    searchable INTEGER NOT NULL DEFAULT 0 CHECK (searchable IN (0, 1)),
    source_id TEXT COLLATE "C" NOT NULL REFERENCES source(id) DEFERRABLE INITIALLY IMMEDIATE,
    batch_id TEXT COLLATE "C" REFERENCES ingestion_batch(id) DEFERRABLE INITIALLY IMMEDIATE,
    run_id TEXT COLLATE "C" REFERENCES analytical_run(id) DEFERRABLE INITIALLY IMMEDIATE,
    fragment_id TEXT COLLATE "C" REFERENCES evidence_fragment(id) DEFERRABLE INITIALLY IMMEDIATE,
    updated_at TEXT COLLATE "C" NOT NULL,
    sort_text_folded TEXT COLLATE "C",
    sort_text_exact TEXT COLLATE "C",
    sort_number DOUBLE PRECISION,
    UNIQUE (node_id, attribute_name)
);
CREATE INDEX node_attribute_lookup_idx ON node_attribute(attribute_name, json_type, value_json);
CREATE INDEX node_attribute_text_sort_idx ON node_attribute(json_type, sort_text_folded, sort_text_exact);
CREATE INDEX node_attribute_number_sort_idx ON node_attribute(json_type, sort_number);

CREATE TABLE relation (
    id TEXT COLLATE "C" PRIMARY KEY,
    source_node_id TEXT COLLATE "C" NOT NULL REFERENCES node(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    type TEXT COLLATE "C" NOT NULL,
    target_node_id TEXT COLLATE "C" NOT NULL REFERENCES node(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    logical_key TEXT COLLATE "C" NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    source_id TEXT COLLATE "C" NOT NULL REFERENCES source(id) DEFERRABLE INITIALLY IMMEDIATE,
    batch_id TEXT COLLATE "C" REFERENCES ingestion_batch(id) DEFERRABLE INITIALLY IMMEDIATE,
    run_id TEXT COLLATE "C" REFERENCES analytical_run(id) DEFERRABLE INITIALLY IMMEDIATE,
    fragment_id TEXT COLLATE "C" REFERENCES evidence_fragment(id) DEFERRABLE INITIALLY IMMEDIATE,
    updated_at TEXT COLLATE "C" NOT NULL,
    UNIQUE (source_node_id, type, target_node_id, logical_key)
);
CREATE INDEX relation_source_idx ON relation(source_node_id, type, active);
CREATE INDEX relation_target_idx ON relation(target_node_id, type, active);

CREATE TABLE metric (
    id TEXT COLLATE "C" PRIMARY KEY,
    run_id TEXT COLLATE "C" NOT NULL REFERENCES analytical_run(id) DEFERRABLE INITIALLY IMMEDIATE,
    definition_version TEXT COLLATE "C" NOT NULL,
    value_json TEXT NOT NULL,
    unit TEXT,
    numerator DOUBLE PRECISION,
    denominator DOUBLE PRECISION,
    dimensions_json TEXT NOT NULL,
    dimensions_hash TEXT COLLATE "C" NOT NULL,
    method_version TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    complete INTEGER NOT NULL CHECK (complete IN (0, 1)),
    invalidated INTEGER NOT NULL CHECK (invalidated IN (0, 1)),
    fragment_id TEXT COLLATE "C" REFERENCES evidence_fragment(id) DEFERRABLE INITIALLY IMMEDIATE,
    recorded_at TEXT COLLATE "C" NOT NULL,
    UNIQUE (run_id, definition_version, dimensions_hash)
);
CREATE INDEX metric_current_idx ON metric(definition_version, dimensions_hash, complete, invalidated);

CREATE TABLE entity_declaration (
    entity_type TEXT COLLATE "C" PRIMARY KEY,
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    fields_json TEXT NOT NULL,
    declaration_hash TEXT COLLATE "C" NOT NULL,
    source_id TEXT COLLATE "C" REFERENCES source(id) DEFERRABLE INITIALLY IMMEDIATE,
    fragment_id TEXT COLLATE "C" REFERENCES evidence_fragment(id) DEFERRABLE INITIALLY IMMEDIATE,
    recorded_at TEXT COLLATE "C" NOT NULL
);

CREATE TABLE observed_field (
    entity_type TEXT COLLATE "C" NOT NULL,
    field_name TEXT COLLATE "C" NOT NULL,
    json_type TEXT NOT NULL CHECK (json_type IN ('unresolved', 'string', 'number', 'boolean', 'object', 'array')),
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    required INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0, 1)),
    nullable INTEGER NOT NULL DEFAULT 1 CHECK (nullable IN (0, 1)),
    searchable INTEGER NOT NULL DEFAULT 0 CHECK (searchable IN (0, 1)),
    declared INTEGER NOT NULL DEFAULT 0 CHECK (declared IN (0, 1)),
    first_batch_id TEXT COLLATE "C" REFERENCES ingestion_batch(id) DEFERRABLE INITIALLY IMMEDIATE,
    last_batch_id TEXT COLLATE "C" REFERENCES ingestion_batch(id) DEFERRABLE INITIALLY IMMEDIATE,
    PRIMARY KEY (entity_type, field_name)
);

CREATE TABLE ontology_declaration (
    name TEXT COLLATE "C" PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind = 'join'),
    relation_type TEXT COLLATE "C" NOT NULL,
    from_entity TEXT COLLATE "C" NOT NULL,
    from_fields_json TEXT NOT NULL,
    to_entity TEXT COLLATE "C" NOT NULL,
    to_fields_json TEXT NOT NULL,
    definition_hash TEXT COLLATE "C" NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    source_id TEXT COLLATE "C" NOT NULL REFERENCES source(id) DEFERRABLE INITIALLY IMMEDIATE,
    fragment_id TEXT COLLATE "C" REFERENCES evidence_fragment(id) DEFERRABLE INITIALLY IMMEDIATE,
    recorded_at TEXT COLLATE "C" NOT NULL
);

CREATE TABLE search_document (
    id TEXT COLLATE "C" PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind = 'node_attribute'),
    target_id TEXT COLLATE "C" NOT NULL REFERENCES node_attribute(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content TEXT NOT NULL,
    content_hash TEXT COLLATE "C" NOT NULL,
    extraction_version TEXT NOT NULL,
    privacy_class TEXT NOT NULL CHECK (privacy_class IN ('public', 'private')),
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ('active', 'stale')),
    recorded_at TEXT COLLATE "C" NOT NULL,
    UNIQUE (target_kind, target_id, chunk_index, extraction_version)
);

CREATE TABLE search_document_fts (
    document_id TEXT COLLATE "C" PRIMARY KEY,
    content TEXT NOT NULL,
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
);
CREATE INDEX search_document_fts_tsv_idx ON search_document_fts USING GIN(content_tsv);

CREATE TABLE embedding_profile (
    id TEXT COLLATE "C" PRIMARY KEY,
    attribute_name TEXT COLLATE "C" NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    preprocessing_version TEXT NOT NULL,
    similarity TEXT NOT NULL CHECK (similarity = 'cosine'),
    privacy_ceiling TEXT NOT NULL CHECK (privacy_ceiling = 'public'),
    contract_hash TEXT COLLATE "C" NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'building', 'ready', 'degraded')),
    last_error TEXT,
    created_at TEXT COLLATE "C" NOT NULL
);

CREATE TABLE embedding_record (
    id TEXT COLLATE "C" PRIMARY KEY,
    search_document_id TEXT COLLATE "C" NOT NULL REFERENCES search_document(id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
    profile_id TEXT COLLATE "C" NOT NULL REFERENCES embedding_profile(id) DEFERRABLE INITIALLY IMMEDIATE,
    input_content_hash TEXT COLLATE "C" NOT NULL,
    vector_blob BYTEA NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    response_model TEXT NOT NULL,
    created_at TEXT COLLATE "C" NOT NULL,
    UNIQUE (search_document_id, profile_id, input_content_hash)
);
CREATE INDEX embedding_record_profile_idx ON embedding_record(profile_id, search_document_id);
