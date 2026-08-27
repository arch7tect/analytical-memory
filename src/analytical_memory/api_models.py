from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from analytical_memory.limits import (
    MAX_QUERY_PATTERN_EDGES,
    MAX_QUERY_PATTERN_NODES,
    MAX_QUERY_RESULTS,
)


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class WireModel(APIModel):
    model_config = ConfigDict(
        extra="forbid", validate_by_alias=True, validate_by_name=False
    )


JsonType = Literal["unresolved", "string", "number", "boolean", "object", "array"]
DeclaredJsonType = Literal["string", "number", "boolean", "object", "array"]
PrivacyClass = Literal["public", "private"]
QueryComparisonOperator = Literal["eq", "ne", "lt", "lte", "gt", "gte"]
QueryInOperator = Literal["in"]
QueryExistsOperator = Literal["exists"]
QUERY_OPERATORS = frozenset(
    (
        *get_args(QueryComparisonOperator),
        *get_args(QueryInOperator),
        *get_args(QueryExistsOperator),
    )
)


class FieldDeclarationInput(APIModel):
    description: str | None = Field(default=None, min_length=1)
    type: DeclaredJsonType | None = None
    required: bool = False
    nullable: bool = True
    privacy: PrivacyClass | None = None
    searchable: bool = False


class KeyFieldInput(APIModel):
    field: str = Field(min_length=1)
    type: Literal["string", "number", "boolean"]


class JoinEndpointInput(APIModel):
    type: str = Field(min_length=3)
    fields: list[str] = Field(min_length=1)


class OntologyProvenance(APIModel):
    fragment_id: str | None
    recorded_at: str
    source_id: str | None


class OntologyField(APIModel):
    description: str | None
    type: JsonType
    privacy: PrivacyClass
    declared: bool
    required: bool
    nullable: bool
    searchable: bool


class OntologyEntity(APIModel):
    type: str
    description: str | None
    privacy: PrivacyClass
    declared: bool
    fields: dict[str, OntologyField]
    provenance: OntologyProvenance | None


class OntologyRelationStatistics(APIModel):
    active_edges: int
    inactive_edges: int


class OntologyRelation(APIModel):
    name: str
    relation: str
    description: str | None
    from_: JoinEndpointInput = Field(alias="from")
    to: JoinEndpointInput
    enabled: bool
    statistics: OntologyRelationStatistics
    provenance: OntologyProvenance


class OntologyStatistics(APIModel):
    nodes: int
    attributes: int
    active_relations: int


class OntologyNamespace(APIModel):
    name: str
    description: str | None
    declared: bool
    provenance: OntologyProvenance | None


class OntologyDocument(APIModel):
    ontology_version: Literal["2"]
    namespaces: list[OntologyNamespace]
    entities: list[OntologyEntity]
    relations: list[OntologyRelation]
    ontology_fingerprint: str
    statistics: OntologyStatistics


class OntologyResponse(APIModel):
    contract_fingerprint: str
    document: OntologyDocument
    ontology_fingerprint: str


class QueryNodePattern(WireModel):
    type: str = Field(min_length=3)
    alias: str = Field(alias="as", min_length=1)


class QueryEdgePattern(WireModel):
    type: str = Field(min_length=1)
    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)
    logical_key: str | None = Field(default=None, min_length=1)


class QueryMatch(APIModel):
    nodes: list[QueryNodePattern] = Field(
        min_length=1, max_length=MAX_QUERY_PATTERN_NODES
    )
    edges: list[QueryEdgePattern] = Field(
        default_factory=list, max_length=MAX_QUERY_PATTERN_EDGES
    )


class QueryFieldOperand(APIModel):
    field: str = Field(min_length=3)


class QueryValueOperand(APIModel):
    value: Any


class QueryValuesOperand(APIModel):
    values: list[Any] = Field(min_length=1)


class QueryComparisonPredicate(APIModel):
    left: QueryFieldOperand
    op: QueryComparisonOperator
    right: QueryValueOperand


class QueryInPredicate(APIModel):
    left: QueryFieldOperand
    op: QueryInOperator
    right: QueryValuesOperand


class QueryExistsPredicate(APIModel):
    left: QueryFieldOperand
    op: QueryExistsOperator


QueryPredicate = QueryComparisonPredicate | QueryInPredicate | QueryExistsPredicate


class QueryFieldProjection(APIModel):
    field: str = Field(min_length=3)


class QueryCountProjection(APIModel):
    count: Literal[True]


QueryProjection = QueryFieldProjection | QueryCountProjection


class QueryOrderBy(APIModel):
    field: str = Field(min_length=3)
    direction: Literal["asc", "desc"] = "asc"


class QueryIRDocument(WireModel):
    query_ir_version: Literal["1"]
    match: QueryMatch
    where: list[QueryPredicate] = Field(default_factory=list)
    return_: list[QueryProjection] = Field(alias="return", min_length=1)
    order_by: list[QueryOrderBy] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=MAX_QUERY_RESULTS)
    offset: int = Field(default=0, ge=0)


class JsonlImportResponse(APIModel):
    attributes_written: int
    batch_id: str
    contract_fingerprint: str
    created_nodes: int
    evidence_availability: Literal["present", "missing"]
    evidence_digest: str
    evidence_verification: Literal["unverified", "verified", "corrupt"]
    fragment_id: str
    idempotency_key: str
    ontology_delta: dict[str, list[str]]
    ontology_fingerprint: str
    records: int
    replayed: bool
    run_id: str
    source_id: str
    updated_nodes: int


class AnalyticalAttributeResponse(APIModel):
    attribute_id: str
    contract_fingerprint: str
    evidence_digest: str
    fragment_id: str
    idempotency_key: str
    ontology_fingerprint: str
    replayed: bool
    run_id: str
    source_id: str


class AnalyticalMetricResponse(APIModel):
    contract_fingerprint: str
    evidence_digest: str
    fragment_id: str
    idempotency_key: str
    metric_id: str
    replayed: bool
    run_id: str
    source_id: str


class JoinMaterializationResponse(APIModel):
    batch_id: str
    contract_fingerprint: str
    created_relations: int
    declaration_created: bool
    definition_hash: str
    name: str
    ontology_fingerprint: str
    previously_materialized_active: int
    previously_materialized_inactive: int
    replayed: bool
    run_id: str
    skipped_null_or_missing: int
    skipped_unmatched: int
    source_id: str


class QueryProjectionResult(APIModel):
    batch_id: str | None
    field: str
    fragment_id: str | None
    json_type: JsonType
    node_id: str
    record_id: str | None
    run_id: str | None
    source_id: str | None
    updated_at: str | None
    value: Any


class QueryRow(APIModel):
    bindings: dict[str, str]
    projections: list[QueryProjectionResult]


class QueryEffectiveOrdering(APIModel):
    direction: Literal["asc", "desc"]
    field: str | None = None
    tie_breaker: str | None = None


class QueryIRResponse(APIModel):
    contract_fingerprint: str
    count: int | None = None
    ontology_fingerprint: str
    ordering: list[QueryEffectiveOrdering]
    rows: list[QueryRow]
    truncated: bool


class NodeDeleteResponse(APIModel):
    attributes: int
    embeddings: int
    nodes: int
    relations: int
    search_documents: int


class EvidenceReadStatus(APIModel):
    availability: Literal["present", "missing"]
    byte_size: int | None
    verification: Literal["verified", "corrupt", "unverified"]


class DirectEvidenceSummary(APIModel):
    digest: str
    byte_size: int
    media_type: str
    status: EvidenceReadStatus


class AttributeExplanation(APIModel):
    attribute_id: str
    attribute_name: str
    batch_id: str | None
    fragment_id: str | None
    json_type: str
    node_id: str
    privacy_class: Literal["public", "private"]
    run_id: str | None
    searchable: bool
    source_id: str
    updated_at: str
    value: Any


class DirectSourceSummary(APIModel):
    id: str
    kind: str
    locator: str


class DirectNodeSummary(APIModel):
    id: str
    namespace: str
    type: str


class ExplanationResponse(APIModel):
    attribute: AttributeExplanation
    evidence: DirectEvidenceSummary | None
    node: DirectNodeSummary
    source: DirectSourceSummary
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
    display_label: str | None = None
    privacy_class: Literal["public", "private"]


class RelationFact(APIModel):
    relation_id: str
    relation_type: str
    logical_key: str
    source: RelationNode
    target: RelationNode
    active: bool
    privacy_class: Literal["public", "private"]


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


class DirectRelationExplanation(APIModel):
    active: bool
    batch_id: str | None
    fragment_id: str | None
    logical_key: str
    privacy_class: Literal["public", "private"]
    relation_id: str
    relation_type: str
    run_id: str | None
    source_id: str
    source_node_id: str
    target_node_id: str
    updated_at: str


class RelationExplanationResponse(APIModel):
    evidence: DirectEvidenceSummary | None
    relation: DirectRelationExplanation
    source: DirectSourceSummary
    schema_fingerprint: str


class MetricExplanationResult(APIModel):
    metric_id: str
    run_id: str
    definition_version: str
    value: Any
    unit: str | None
    numerator: float | None
    denominator: float | None
    dimensions: dict[str, Any]
    method_version: str
    coverage: dict[str, Any]
    recorded_at: str
    fragment_id: str | None
    complete: bool
    invalidated: bool


class DirectRunSummary(APIModel):
    id: str
    batch_id: str | None
    source_id: str
    method: str
    recorded_at: str


class MetricExplanationResponse(APIModel):
    metric: MetricExplanationResult
    evidence: DirectEvidenceSummary | None
    source: DirectSourceSummary
    run: DirectRunSummary
    schema_fingerprint: str


class SearchCoverage(APIModel):
    eligible_count: int
    indexed_count: int
    complete: bool


class SearchMatch(APIModel):
    document_id: str
    target_kind: Literal["node_attribute"]
    target_id: str
    content: str
    content_hash: str
    privacy_class: Literal["public", "private"]
    rank: float
    value: Any
    json_type: str
    source_id: str
    batch_id: str | None
    run_id: str | None
    fragment_id: str | None
    updated_at: str


class SearchResponse(APIModel):
    query: Literal["search-text"]
    text: str
    results: list[SearchMatch]
    coverage: SearchCoverage
    schema_fingerprint: str


class EmbeddingProfile(APIModel):
    id: str
    attribute_name: str
    provider: str
    model: str
    dimensions: int
    preprocessing_version: str
    similarity: Literal["cosine"]
    privacy_ceiling: Literal["public"]
    contract_hash: str
    status: Literal["pending", "building", "ready", "degraded"]
    last_error: str | None
    created_at: str


class EmbeddingProviderReadiness(APIModel):
    configured: bool
    matches: bool


class EmbeddingProfileResponse(APIModel):
    profile: EmbeddingProfile
    coverage: SearchCoverage
    provider: EmbeddingProviderReadiness
    schema_fingerprint: str


class SemanticSearchMatch(APIModel):
    attribute_name: str
    content: str
    content_hash: str
    document_id: str
    value: Any
    json_type: str
    namespace: str
    node_type: str
    privacy_class: Literal["public"]
    source_id: str
    batch_id: str | None
    run_id: str | None
    fragment_id: str | None
    updated_at: str
    score: float
    target_id: str
    target_kind: Literal["node_attribute"]


class SemanticSearchResponse(APIModel):
    coverage: SearchCoverage
    profile_id: str
    query: Literal["search-semantic"]
    results: list[SemanticSearchMatch]
    schema_fingerprint: str
    status: Literal["ready", "degraded"]
    text: str


class EvidenceStatusResponse(APIModel):
    availability: Literal["present", "missing"]
    byte_size: int | None
    digest: str
    effective_privacy: Literal["public", "private"]
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
    orphans: list[dict[str, Any]]
    results: list[EvidenceVerifyResponse]
    truncated: bool
