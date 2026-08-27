from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class EmbeddingProviderInfo:
    provider: str
    model: str
    dimensions: int
    preprocessing_version: str
    privacy_ceiling: str
    configured: bool


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    vectors: tuple[tuple[float, ...], ...]
    response_model: str


@dataclass(frozen=True, slots=True)
class EmbeddingProfileRecord:
    id: str
    attribute_name: str
    provider: str
    model: str
    dimensions: int
    preprocessing_version: str
    similarity: str
    privacy_ceiling: str
    contract_hash: str
    status: str
    last_error: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class EmbeddingRecord:
    id: str
    search_document_id: str
    profile_id: str
    input_content_hash: str
    vector_blob: bytes
    dimensions: int
    response_model: str
    created_at: str


@dataclass(frozen=True, slots=True)
class EvidenceObjectRecord:
    id: str
    digest: str
    byte_size: int
    media_type: str
    privacy_class: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class EvidenceFragmentRecord:
    id: str
    evidence_object_id: str
    locator_kind: str
    locator_json: str
    extractor_id: str
    extractor_version: str
    byte_size: int
    digest: str
    privacy_class: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class StoredBatch:
    input_hash: str
    result: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EvidenceStatus:
    availability: str
    verification: str
    digest: str
    byte_size: int | None


@dataclass(frozen=True, slots=True)
class MemoryStoreStatus:
    backend: str
    initialized: bool
    schema_version: int


@dataclass(frozen=True, slots=True)
class EvidenceStoreStatus:
    provider: str
    initialized: bool


@dataclass(frozen=True, slots=True)
class KeyField:
    field: str
    type: str


@dataclass(frozen=True, slots=True)
class FieldDeclaration:
    name: str
    description: str | None = None
    type: str | None = None
    required: bool = False
    nullable: bool = True
    privacy: str | None = None
    searchable: bool = False


@dataclass(frozen=True, slots=True)
class EntityDeclaration:
    entity_type: str
    description: str | None = None
    privacy: str = "public"
    fields: tuple[FieldDeclaration, ...] = ()


@dataclass(frozen=True, slots=True)
class NamespaceDeclaration:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class JsonlImportRequest:
    entity_type: str
    key: tuple[KeyField, ...]
    source_path: Path
    contract_fingerprint: str


@dataclass(frozen=True, slots=True)
class JsonlScan:
    spool_path: Path
    content_hash: str
    byte_size: int
    record_count: int
    field_types: dict[str, str]
    present_counts: dict[str, int]
    null_fields: frozenset[str]


@dataclass(frozen=True, slots=True)
class ImportEvidence:
    object: EvidenceObjectRecord
    fragment: EvidenceFragmentRecord
    created: bool


@dataclass(frozen=True, slots=True)
class AnalyticalAttributeRequest:
    node_id: str
    attribute_name: str
    value: Any
    method: str
    privacy: str
    searchable: bool
    contract_fingerprint: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class AnalyticalMetricRequest:
    definition_version: str
    value: Any
    dimensions: dict[str, Any]
    method: str
    method_version: str
    coverage: dict[str, Any]
    complete: bool
    unit: str | None
    numerator: float | None
    denominator: float | None
    privacy: str
    contract_fingerprint: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class JoinEndpoint:
    type: str
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JoinRequest:
    name: str
    relation: str
    description: str | None
    from_: JoinEndpoint
    to: JoinEndpoint
    contract_fingerprint: str
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class QueryPlan:
    node_aliases: tuple[tuple[str, str], ...]
    edges: tuple[dict[str, str], ...]
    predicates: tuple[dict[str, Any], ...]
    projections: tuple[dict[str, Any], ...]
    order_by: tuple[dict[str, str], ...]
    limit: int
    offset: int
    count: bool


@dataclass(frozen=True, slots=True)
class EvidencePutResult:
    status: EvidenceStatus
    created: bool
