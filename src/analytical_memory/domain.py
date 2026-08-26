from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceRecord:
    id: str
    natural_key: str
    kind: str
    locator: str
    privacy_class: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    idempotency_key: str
    batch_id: str
    source_id: str
    valid_from: str
    valid_to: str | None
    method: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class NodeRecord:
    id: str
    namespace: str
    type: str
    natural_key: str
    display_label: str | None
    privacy_class: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class AttributeRecord:
    id: str
    node_id: str
    name: str
    cardinality: str
    value_json: str
    value_hash: str
    searchable: int
    privacy_class: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class RelationRecord:
    id: str
    source_node_id: str
    type: str
    target_node_id: str
    logical_key: str
    privacy_class: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class AssertionRecord:
    id: str
    target_kind: str
    target_id: str
    attribute_id: str | None
    relation_id: str | None
    stance: str
    basis: str
    confidence: float
    review_status: str
    valid_from: str
    valid_to: str | None
    recorded_at: str
    method: str
    source_id: str
    run_id: str
    supersedes_assertion_id: str | None
    lifecycle: str
    stable_key: str
    stable_key_version: int


@dataclass(frozen=True, slots=True)
class MetricRecord:
    id: str
    run_id: str
    definition_version: str
    value_json: str
    unit: str | None
    numerator: float | None
    denominator: float | None
    dimensions_json: str
    dimensions_hash: str
    method_version: str
    coverage_json: str
    complete: int
    invalidated: int
    recorded_at: str


@dataclass(frozen=True, slots=True)
class SearchDocumentRecord:
    id: str
    target_kind: str
    target_id: str
    chunk_index: int
    content: str
    content_hash: str
    extraction_version: str
    privacy_class: str
    lifecycle: str
    recorded_at: str


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
class EvidenceAcquisitionRecord:
    id: str
    evidence_object_id: str
    source_id: str
    run_id: str
    privacy_class: str
    retention_required: int
    retain_until: str | None
    method: str
    review_status: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class EvidenceLocationRecord:
    id: str
    evidence_object_id: str
    provider: str
    root_id: str
    object_key: str
    availability: str
    verified_at: str | None
    recorded_at: str


@dataclass(frozen=True, slots=True)
class EvidenceVerificationRecord:
    id: str
    target_kind: str
    target_id: str
    digest: str
    outcome: str
    byte_size: int | None
    method: str
    checked_at: str


@dataclass(frozen=True, slots=True)
class EvidenceDerivationRecord:
    id: str
    input_object_id: str
    output_object_id: str
    method: str
    method_version: str
    parameters_json: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class EvidenceBindingRecord:
    id: str
    target_kind: str
    target_id: str
    assertion_id: str | None
    metric_id: str | None
    fragment_id: str
    role: str
    confidence: float
    review_status: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class PreparedEvidence:
    source_path: Path
    object: EvidenceObjectRecord
    materialized_objects: tuple[tuple[EvidenceObjectRecord, bytes], ...]
    fragment: EvidenceFragmentRecord
    acquisitions: tuple[EvidenceAcquisitionRecord, ...]
    locations: tuple[EvidenceLocationRecord, ...]
    verifications: tuple[EvidenceVerificationRecord, ...]
    derivations: tuple[EvidenceDerivationRecord, ...]


@dataclass(frozen=True, slots=True)
class BatchPlan:
    id: str
    idempotency_key: str
    input_hash: str
    schema_fingerprint: str
    recorded_at: str
    source: SourceRecord
    run: RunRecord
    evidence: PreparedEvidence
    nodes: tuple[NodeRecord, ...]
    attributes: tuple[AttributeRecord, ...]
    relations: tuple[RelationRecord, ...]
    assertions: tuple[AssertionRecord, ...]
    metrics: tuple[MetricRecord, ...]
    search_documents: tuple[SearchDocumentRecord, ...]
    bindings: tuple[EvidenceBindingRecord, ...]

    def result(self) -> dict[str, Any]:
        return {
            "attribute_ids": [record.id for record in self.attributes],
            "batch_id": self.id,
            "evidence_digest": self.evidence.object.digest,
            "fragment_id": self.evidence.fragment.id,
            "metric_ids": [record.id for record in self.metrics],
            "node_ids": [record.id for record in self.nodes],
            "relation_ids": [record.id for record in self.relations],
            "run_id": self.run.id,
            "schema_fingerprint": self.schema_fingerprint,
            "search_document_ids": [record.id for record in self.search_documents],
        }

    def preview(self) -> dict[str, Any]:
        return {
            "counts": {
                "assertions": len(self.assertions),
                "attributes": len(self.attributes),
                "bindings": len(self.bindings),
                "derivations": len(self.evidence.derivations),
                "evidence_acquisitions": len(self.evidence.acquisitions),
                "evidence_locations": len(self.evidence.locations),
                "evidence_objects": 1 + len(self.evidence.materialized_objects),
                "evidence_verifications": len(self.evidence.verifications),
                "metrics": len(self.metrics),
                "nodes": len(self.nodes),
                "relations": len(self.relations),
                "runs": 1,
                "search_documents": len(self.search_documents),
                "sources": 1,
            },
            "plan": self.result(),
            "writes": False,
        }

    def debug_dict(self) -> dict[str, Any]:
        return asdict(self)


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
