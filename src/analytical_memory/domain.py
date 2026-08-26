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
    privacy_class: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class AssertionRecord:
    id: str
    attribute_id: str
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
class EvidenceBindingRecord:
    id: str
    assertion_id: str
    fragment_id: str
    role: str
    confidence: float
    review_status: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class PreparedEvidence:
    source_path: Path
    object: EvidenceObjectRecord
    fragment: EvidenceFragmentRecord


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
    assertions: tuple[AssertionRecord, ...]
    bindings: tuple[EvidenceBindingRecord, ...]

    def result(self) -> dict[str, Any]:
        return {
            "attribute_ids": [record.id for record in self.attributes],
            "batch_id": self.id,
            "evidence_digest": self.evidence.object.digest,
            "node_ids": [record.id for record in self.nodes],
            "run_id": self.run.id,
            "schema_fingerprint": self.schema_fingerprint,
        }

    def preview(self) -> dict[str, Any]:
        return {
            "counts": {
                "assertions": len(self.assertions),
                "attributes": len(self.attributes),
                "bindings": len(self.bindings),
                "evidence_objects": 1,
                "nodes": len(self.nodes),
                "runs": 1,
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
