ALTER TABLE evidence_binding RENAME TO evidence_binding_v2;
ALTER TABLE evidence_fragment RENAME TO evidence_fragment_v2;

CREATE TABLE evidence_acquisition (
    id TEXT PRIMARY KEY,
    evidence_object_id TEXT NOT NULL REFERENCES evidence_object(id),
    source_id TEXT NOT NULL REFERENCES source(id),
    run_id TEXT NOT NULL REFERENCES analytical_run(id),
    privacy_class TEXT NOT NULL,
    retention_required INTEGER NOT NULL CHECK (retention_required IN (0, 1)),
    retain_until TEXT,
    method TEXT NOT NULL,
    review_status TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (evidence_object_id, run_id)
) STRICT;

CREATE TABLE evidence_derivation (
    id TEXT PRIMARY KEY,
    input_object_id TEXT NOT NULL REFERENCES evidence_object(id),
    output_object_id TEXT NOT NULL REFERENCES evidence_object(id),
    method TEXT NOT NULL,
    method_version TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (input_object_id, output_object_id, method, method_version, parameters_json)
) STRICT;

CREATE TABLE evidence_location (
    id TEXT PRIMARY KEY,
    evidence_object_id TEXT NOT NULL REFERENCES evidence_object(id),
    provider TEXT NOT NULL,
    root_id TEXT NOT NULL,
    object_key TEXT NOT NULL,
    availability TEXT NOT NULL CHECK (availability IN ('present', 'missing')),
    verified_at TEXT,
    recorded_at TEXT NOT NULL,
    UNIQUE (evidence_object_id, provider, root_id, object_key)
) STRICT;

CREATE TABLE evidence_verification (
    id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (
        target_kind IN ('object', 'fragment', 'snapshot', 'import')
    ),
    target_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('verified', 'corrupt', 'missing')),
    byte_size INTEGER CHECK (byte_size IS NULL OR byte_size >= 0),
    method TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    UNIQUE (target_kind, target_id, checked_at, method)
) STRICT;

CREATE TABLE evidence_retirement (
    evidence_object_id TEXT PRIMARY KEY REFERENCES evidence_object(id),
    digest TEXT NOT NULL UNIQUE,
    plan_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    retired_at TEXT NOT NULL
) STRICT;

CREATE TABLE evidence_fragment (
    id TEXT PRIMARY KEY,
    evidence_object_id TEXT NOT NULL REFERENCES evidence_object(id),
    locator_kind TEXT NOT NULL CHECK (
        locator_kind IN (
            'whole_object', 'structured', 'record_key', 'byte_range',
            'line_range', 'time_interval', 'sample_interval'
        )
    ),
    locator_json TEXT NOT NULL,
    extractor_id TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    digest TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (
        evidence_object_id, locator_kind, locator_json, extractor_id,
        extractor_version
    )
) STRICT;

INSERT INTO evidence_fragment SELECT * FROM evidence_fragment_v2;

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

INSERT INTO evidence_binding SELECT * FROM evidence_binding_v2;

DROP TABLE evidence_binding_v2;
DROP TABLE evidence_fragment_v2;

CREATE INDEX evidence_acquisition_object_idx
    ON evidence_acquisition(evidence_object_id, retention_required, retain_until);
CREATE INDEX evidence_location_object_idx ON evidence_location(evidence_object_id);
CREATE INDEX evidence_verification_target_idx
    ON evidence_verification(target_kind, target_id, checked_at);

PRAGMA user_version = 3;
