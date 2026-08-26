from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngestionResult(APIModel):
    attribute_ids: list[str]
    batch_id: str
    evidence_digest: str
    node_ids: list[str]
    run_id: str
    schema_fingerprint: str


class PreviewCounts(APIModel):
    assertions: int
    attributes: int
    bindings: int
    evidence_objects: int
    nodes: int
    runs: int
    sources: int


class PreviewResponse(APIModel):
    counts: PreviewCounts
    plan: IngestionResult
    writes: bool


class ApplyResponse(APIModel):
    replayed: bool
    result: IngestionResult


class Fact(APIModel):
    attribute_id: str
    attribute_name: str
    namespace: str
    natural_key: str
    node_type: str
    privacy_class: Literal["public", "private", "restricted", "forbidden"]
    state: Literal["supported", "contested", "contradicted", "unasserted"]
    value: Any


class CurrentFactsResponse(APIModel):
    query: str
    results: list[Fact]
    schema_fingerprint: str


class EvidenceObjectSummary(APIModel):
    byte_size: int
    digest: str
    media_type: str
    privacy_class: Literal["public", "private", "restricted", "forbidden"]


class ExtractorSummary(APIModel):
    id: str
    version: str


class EvidenceReadStatus(APIModel):
    availability: Literal["present", "missing"]
    byte_size: int | None
    verification: Literal["verified", "corrupt", "unverified"]


class WholeObjectLocator(APIModel):
    kind: Literal["whole_object"]


class EvidenceBindingSummary(APIModel):
    binding_id: str
    extractor: ExtractorSummary
    fragment_id: str
    locator: WholeObjectLocator
    locator_kind: Literal["whole_object"]
    object: EvidenceObjectSummary
    role: Literal["supports", "contradicts", "contextualizes"]
    status: EvidenceReadStatus


class AssertionExplanation(APIModel):
    assertion_id: str
    basis: Literal["observed", "computed", "inferred", "declared"]
    confidence: float
    effective: bool
    evidence: list[EvidenceBindingSummary]
    method: str
    recorded_at: str
    review_status: str
    run_id: str
    source_id: str
    stance: Literal["supports", "contradicts"]
    supersedes_assertion_id: str | None
    valid_from: str
    valid_to: str | None


class NodeSummary(APIModel):
    id: str
    namespace: str
    natural_key: str
    type: str


class ExplanationResponse(APIModel):
    assertions: list[AssertionExplanation]
    fact: Fact
    node: NodeSummary
    schema_fingerprint: str
