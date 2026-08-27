CREATE TABLE embedding_profile (
    id TEXT PRIMARY KEY,
    attribute_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    preprocessing_version TEXT NOT NULL,
    similarity TEXT NOT NULL CHECK (similarity = 'cosine'),
    privacy_ceiling TEXT NOT NULL CHECK (
        privacy_ceiling IN ('public', 'private', 'restricted', 'forbidden')
    ),
    contract_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'building', 'ready', 'degraded')
    ),
    last_error TEXT,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE embedding_record (
    id TEXT PRIMARY KEY,
    search_document_id TEXT NOT NULL REFERENCES search_document(id),
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

PRAGMA user_version = 4;
