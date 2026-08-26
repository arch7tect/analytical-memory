from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngestionResult(APIModel):
    attribute_ids: list[str]
    batch_id: str
    evidence_digest: str
    fragment_id: str
    metric_ids: list[str]
    node_ids: list[str]
    relation_ids: list[str]
    run_id: str
    schema_fingerprint: str
    search_document_ids: list[str]


class PreviewCounts(APIModel):
    assertions: int
    attributes: int
    bindings: int
    derivations: int
    evidence_acquisitions: int
    evidence_locations: int
    evidence_objects: int
    evidence_verifications: int
    metrics: int
    nodes: int
    relations: int
    runs: int
    search_documents: int
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


class EvidenceFragmentSummary(APIModel):
    digest: str
    byte_size: int
    privacy_class: Literal["public", "private", "restricted", "forbidden"]


class WholeObjectLocator(APIModel):
    kind: Literal["whole_object"]


class StructuredLocator(APIModel):
    input_format: Literal["canonical-json"]
    kind: Literal["structured"]
    pointer: str


class RecordKeyLocator(APIModel):
    input_format: Literal["canonical-jsonl"]
    key_field: str
    key_value: Any
    kind: Literal["record_key"]


class ByteRangeLocator(APIModel):
    end: int
    kind: Literal["byte_range"]
    start: int


class LineRangeLocator(APIModel):
    end_line: int
    kind: Literal["line_range"]
    start_line: int


class TimeIntervalLocator(APIModel):
    end: str
    input_format: Literal["canonical-jsonl"]
    kind: Literal["time_interval"]
    start: str
    timestamp_field: str


class SampleIntervalLocator(APIModel):
    bit_width: int
    byte_order: str
    channels: int
    end_sample: int
    interleaved: bool
    kind: Literal["sample_interval"]
    sample_format: str
    sample_rate: int
    start_sample: int


EvidenceLocator = Annotated[
    WholeObjectLocator
    | StructuredLocator
    | RecordKeyLocator
    | ByteRangeLocator
    | LineRangeLocator
    | TimeIntervalLocator
    | SampleIntervalLocator,
    Field(discriminator="kind"),
]

LocatorKind = Literal[
    "whole_object",
    "structured",
    "record_key",
    "byte_range",
    "line_range",
    "time_interval",
    "sample_interval",
]


class EvidenceBindingSummary(APIModel):
    binding_id: str
    extractor: ExtractorSummary
    fragment: EvidenceFragmentSummary
    fragment_id: str
    locator: EvidenceLocator
    locator_kind: LocatorKind
    object: EvidenceObjectSummary
    role: Literal["supports", "contradicts", "contextualizes"]
    status: EvidenceReadStatus


class SourceSummary(APIModel):
    id: str
    kind: str
    locator: str
    privacy_class: Literal["public", "private", "restricted", "forbidden"]


class RunSummary(APIModel):
    id: str
    method: str
    valid_from: str
    valid_to: str | None
    recorded_at: str


class AssertionExplanation(APIModel):
    assertion_id: str
    basis: Literal["observed", "computed", "inferred", "declared"]
    confidence: float
    effective: bool
    evidence: list[EvidenceBindingSummary]
    lifecycle: Literal["active", "superseded", "retracted"]
    method: str
    recorded_at: str
    review_status: str
    run: RunSummary
    run_id: str
    source: SourceSummary
    source_id: str
    stance: Literal["supports", "contradicts"]
    stable_key: str
    stable_key_version: Literal[1, 2]
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


class SlotResult(APIModel):
    node_id: str
    namespace: str
    node_type: str
    natural_key: str
    attribute_name: str
    cardinality: Literal["single", "multi"]
    status: Literal["missing", "current", "contested", "conflict", "values"]
    current_value: Any
    candidates: list[Fact]


class CurrentSlotsResponse(APIModel):
    query: Literal["current-slots"]
    results: list[SlotResult]
    schema_fingerprint: str


class MetricResult(APIModel):
    metric_id: str
    run_id: str
    source_id: str
    definition_version: str
    value: Any
    unit: str | None
    numerator: float | None
    denominator: float | None
    dimensions: dict[str, Any]
    method_version: str
    run_method: str
    coverage: dict[str, Any]
    recorded_at: str


class MetricSelectionCoverage(APIModel):
    complete: bool
    selected_count: int


class CurrentMetricResponse(APIModel):
    query: Literal["current-metric"]
    definition_version: str
    dimensions: dict[str, Any]
    metric: MetricResult | None
    coverage: MetricSelectionCoverage
    schema_fingerprint: str


class RelationNode(APIModel):
    id: str
    namespace: str
    type: str
    natural_key: str


class RelationFact(APIModel):
    relation_id: str
    type: str
    logical_key: str
    source: RelationNode
    target: RelationNode
    state: Literal["supported", "contested", "contradicted", "unasserted"]
    privacy_class: Literal["public", "private", "restricted", "forbidden"]


class TraversalNode(RelationNode):
    depth: int


class TraversalEdge(RelationFact):
    depth: int


class TraversalResponse(APIModel):
    query: Literal["traverse-relations"]
    start_node_id: str
    direction: Literal["outbound", "inbound", "both"]
    max_depth: int
    states: list[str]
    nodes: list[TraversalNode]
    edges: list[TraversalEdge]
    truncated: bool
    schema_fingerprint: str


class RelationExplanationResponse(APIModel):
    fact: RelationFact
    assertions: list[AssertionExplanation]
    schema_fingerprint: str


class MetricExplanationResult(MetricResult):
    complete: bool
    invalidated: bool


class MetricExplanationResponse(APIModel):
    metric: MetricExplanationResult
    evidence: list[EvidenceBindingSummary]
    source: SourceSummary
    run: RunSummary
    schema_fingerprint: str


class SearchCoverage(APIModel):
    eligible_count: int
    indexed_count: int
    complete: bool


class SearchProvenance(APIModel):
    assertions: list[AssertionExplanation]
    node: NodeSummary


class SearchMatch(APIModel):
    document_id: str
    target_kind: Literal["node_attribute"]
    target_id: str
    content: str
    content_hash: str
    privacy_class: Literal["public", "private", "restricted", "forbidden"]
    rank: float
    fact: Fact
    provenance: SearchProvenance


class SearchResponse(APIModel):
    query: Literal["search-text"]
    text: str
    results: list[SearchMatch]
    coverage: SearchCoverage
    schema_fingerprint: str


class EvidenceStatusResponse(APIModel):
    availability: Literal["present", "missing"]
    byte_size: int | None
    digest: str
    effective_privacy: Literal["public", "private", "restricted", "forbidden"]
    retired: bool
    verification: Literal["verified", "corrupt", "unverified"]


class EvidenceReadResponse(APIModel):
    byte_count: int
    data_base64: str
    digest: str
    eof: bool
    limit: int
    offset: int


class FragmentVerificationResult(APIModel):
    expected_digest: str
    fragment_id: str
    outcome: Literal["verified", "corrupt"]
    reproduced_digest: str


class EvidenceVerifyResponse(APIModel):
    availability: Literal["present", "missing"]
    byte_size: int | None
    checked_at: str
    digest: str
    fragments: list[FragmentVerificationResult]
    verification: Literal["verified", "corrupt", "unverified"]


class EvidenceAuditResponse(APIModel):
    checked_at: str
    complete: bool
    results: list[EvidenceVerifyResponse]
    truncated: bool
