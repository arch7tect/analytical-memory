from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from analytical_memory.api_models import (
    AnalyticalAttributeResponse,
    AnalyticalMetricResponse,
    APIModel,
    CurrentMetricResponse,
    DirectRelationExplanation,
    EmbeddingProfileResponse,
    EvidenceAuditResponse,
    EvidenceReadResponse,
    EvidenceStatusResponse,
    EvidenceVerifyResponse,
    ExplanationResponse,
    FieldDeclarationInput,
    JoinEndpointInput,
    JoinMaterializationResponse,
    JsonlImportResponse,
    KeyFieldInput,
    MetricExplanationResponse,
    NodeDeleteResponse,
    OntologyResponse,
    QueryIRDocument,
    QueryIRResponse,
    RelationExplanationResponse,
    SearchResponse,
    SemanticSearchResponse,
    TraversalResponse,
)
from analytical_memory.mcp_schema import describe_response_schema

ContractFingerprint = Annotated[
    str,
    Field(
        description=(
            "This payload field is named contract_fingerprint; its value must equal "
            "the exact schema_fingerprint from memory://schema/current. Refresh and "
            "retry once if the server returns schema_changed."
        )
    ),
]
NodeId = Annotated[
    str,
    Field(
        description=(
            "Canonical Node ID obtained from query bindings, traversal, or another "
            "result in the same memory."
        )
    ),
]
EvidenceDigest = Annotated[
    str,
    Field(description="Lowercase SHA-256 evidence digest from the same memory."),
]


class ConfigureMemoryRequest(APIModel):
    action: Literal["create", "attach"] = Field(
        description=(
            "create initializes a new/empty target; attach validates an existing "
            "initialized target without migrating it."
        )
    )
    name: str = Field(description="New lowercase catalog alias; default is reserved.")
    backend: Literal["sqlite", "postgresql"] = Field(
        description="Storage backend for the named memory."
    )
    evidence_root: str = Field(
        description="Absolute path to the memory's local evidence directory."
    )
    database: str | None = Field(
        default=None,
        description="Absolute SQLite database path; required only for sqlite.",
    )
    connection_env: str | None = Field(
        default=None,
        description=(
            "Per-user environment-variable name containing the PostgreSQL URL; "
            "required only for postgresql."
        ),
    )
    postgres_schema: str | None = Field(
        default=None,
        alias="schema",
        description="Dedicated PostgreSQL schema; required only for postgresql.",
    )


class ExpectedMemoryState(APIModel):
    nodes: int = Field(ge=0, description="Current number of Nodes in the memory.")
    attributes: int = Field(
        ge=0, description="Current number of Node attributes in the memory."
    )
    active_relations: int = Field(
        ge=0, description="Current number of active relations in the memory."
    )
    evidence_objects: int = Field(
        ge=0, description="Current number of catalogued evidence objects."
    )
    fingerprint: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of all canonical rows.",
    )


class MemoryLifecycleRequest(APIModel):
    action: Literal["status", "wipe", "delete"] = Field(
        description=(
            "status reads the guard counts; wipe resets the selected memory; delete "
            "also removes a named target and catalog entry."
        )
    )
    memory: str = Field(
        description="Explicit configured memory name, including default when intended."
    )
    expected_state: ExpectedMemoryState | None = Field(
        default=None,
        description=(
            "Exact counts from action=status; required for wipe/delete and omitted "
            "for status. Any mismatch aborts."
        ),
    )


class DeclareEntityRequest(APIModel):
    entity_type: str = Field(description="Namespaced entity type to declare.")
    contract_fingerprint: ContractFingerprint
    description: str | None = Field(
        default=None, description="Optional human-readable entity meaning."
    )
    privacy: Literal["public", "private"] = Field(
        default="public", description="Default privacy for the entity."
    )
    fields: dict[str, FieldDeclarationInput] | None = Field(
        default=None,
        description="Optional replacement map of declared field constraints.",
    )


class DeclareNamespaceRequest(APIModel):
    namespace: str = Field(description="Namespace prefix used by entity types.")
    description: str = Field(description="Non-empty human-readable namespace meaning.")
    contract_fingerprint: ContractFingerprint


class JsonlImportRequest(APIModel):
    source_path: str = Field(
        description=(
            "Server-local UTF-8 JSONL path containing one JSON object per non-empty "
            "line."
        )
    )
    entity_type: str = Field(description="Namespaced entity type for imported Nodes.")
    key: list[KeyFieldInput] = Field(
        min_length=1,
        description="Ordered typed fields used to find current Nodes during import.",
    )
    contract_fingerprint: ContractFingerprint


class AnalyticalAttributeRequest(APIModel):
    node_id: NodeId
    attribute_name: str = Field(
        description="Current analytical attribute name to create or replace."
    )
    value: Any = Field(description="Canonical JSON analytical value.")
    method: str = Field(description="Stable versioned analysis procedure identifier.")
    contract_fingerprint: ContractFingerprint


class AnalyticalMetricRequest(APIModel):
    definition_version: str = Field(
        description="Stable versioned metric-definition identifier."
    )
    value: Any = Field(description="Canonical JSON metric value.")
    dimensions: dict[str, Any] = Field(
        description="Exact JSON scope used for deterministic current selection."
    )
    method: str = Field(description="Stable analysis procedure name.")
    method_version: str = Field(description="Analysis implementation version.")
    contract_fingerprint: ContractFingerprint
    coverage: dict[str, Any] | None = Field(
        default=None, description="Optional observation coverage summary."
    )
    complete: bool = Field(
        default=True, description="Whether the observation covers its declared scope."
    )
    unit: str | None = Field(default=None, description="Optional metric unit.")
    numerator: float | None = Field(
        default=None, description="Optional ratio numerator."
    )
    denominator: float | None = Field(
        default=None, description="Optional ratio denominator."
    )
    privacy: Literal["public", "private"] = Field(
        default="public", description="Metric observation privacy."
    )


class JoinMaterializeRequest(APIModel):
    name: str = Field(description="Stable join declaration name.")
    relation: str = Field(description="Relation type written on matching edges.")
    from_: JoinEndpointInput = Field(
        alias="from",
        description=(
            "Directed source endpoint. Array fields expand their unique non-null "
            "scalar elements, and multiple arrays form a Cartesian product."
        ),
    )
    to: JoinEndpointInput = Field(
        description="Directed target endpoint with scalar ordered join fields."
    )
    contract_fingerprint: ContractFingerprint
    idempotency_key: str | None = Field(
        default=None, description="Optional caller-stable replay key."
    )
    description: str | None = Field(
        default=None, description="Optional human-readable relation meaning."
    )


class RelationDeactivateRequest(APIModel):
    relation_id: str = Field(
        description="Canonical relation ID returned by traversal or explanation."
    )


class QueryExecuteRequest(APIModel):
    document: QueryIRDocument = Field(
        description="Query IR v1 document using the selected memory ontology."
    )


class CurrentMetricRequest(APIModel):
    definition_version: str = Field(
        description="Exact metric definition version used when writing."
    )
    dimensions: dict[str, Any] = Field(
        description="Exact dimensions object used when writing."
    )


class TraverseRelationsRequest(APIModel):
    start_node_id: NodeId
    relation_types: list[str] | None = Field(
        default=None, description="Optional relation-type filter from the ontology."
    )
    direction: Literal["outbound", "inbound", "both"] = Field(
        default="outbound", description="Edge direction relative to the start Node."
    )
    max_depth: int = Field(
        default=3,
        description="Maximum graph hops; see capabilities.limits.traversal_depth.",
    )
    limit: int = Field(
        default=100,
        description=(
            "Maximum returned items; see capabilities.limits.traversal_results and "
            "check result.truncated."
        ),
    )
    states: list[Literal["active"]] | None = Field(
        default=None, description="Optional lifecycle filter; V1 supports active."
    )


class SearchTextRequest(APIModel):
    query: str = Field(description="Non-empty words or numbers for local text search.")
    limit: int = Field(
        default=20,
        description="Maximum matches; see capabilities.limits.search_results.",
    )


class EmbeddingStatusRequest(APIModel):
    profile_id: str = Field(description="Stored embedding profile identifier.")


class SearchSemanticRequest(APIModel):
    profile_id: str = Field(description="Ready embedding profile identifier.")
    query: str = Field(
        description=(
            "Natural-language query sent to the configured external embedding "
            "provider; do not include private content."
        )
    )
    namespace: str | None = Field(
        default=None, description="Optional exact namespace filter."
    )
    node_type: str | None = Field(
        default=None, description="Optional exact entity-type filter."
    )
    privacy_ceiling: Literal["public"] | None = Field(
        default=None, description="Optional explicit public-only privacy ceiling."
    )
    limit: int = Field(
        default=20,
        description="Maximum matches; see capabilities.limits.search_results.",
    )


class ExplainAttributeRequest(APIModel):
    attribute_id: str = Field(
        description="Current attribute record ID from query, search, or analysis."
    )


class ExplainRelationRequest(APIModel):
    relation_id: str = Field(description="Current relation ID from traversal.")


class ExplainMetricRequest(APIModel):
    metric_id: str = Field(description="Immutable metric observation ID.")


class EvidenceStatusRequest(APIModel):
    digest: EvidenceDigest


class EvidenceReadRequest(APIModel):
    digest: EvidenceDigest
    offset: int = Field(default=0, description="Zero-based evidence byte offset.")
    limit: int = Field(
        default=65536,
        description=(
            "Maximum bytes; see capabilities.evidence.raw_read.max_bytes and check "
            "result.eof."
        ),
    )


class EvidenceVerifyRequest(APIModel):
    digest: EvidenceDigest


class EvidenceAuditRequest(APIModel):
    limit: int = Field(
        default=1000,
        description=(
            "Maximum objects; see capabilities.limits.validated_evidence_objects and "
            "check result.complete and result.truncated."
        ),
    )


class NodeDeleteRequest(APIModel):
    node_id: NodeId
    memory: str | None = Field(
        default=None,
        description=("Configured memory name from memory://catalog; omit for default."),
    )


class MemoryTargetResponse(APIModel):
    backend: Literal["sqlite", "postgresql"] = Field(
        description="Configured storage backend."
    )
    evidence_root: str = Field(description="Resolved absolute evidence-root path.")
    database: str | None = Field(
        default=None, description="Resolved SQLite database path, when applicable."
    )
    connection_env: str | None = Field(
        default=None,
        description="PostgreSQL connection environment-variable name, never its value.",
    )
    postgres_schema: str | None = Field(
        default=None,
        alias="schema",
        description="PostgreSQL schema, when applicable.",
    )


class MemoryConfigureResponse(APIModel):
    action: Literal["create", "attach"] = Field(
        description="Lifecycle action that completed."
    )
    memory: str = Field(description="Configured memory name.")
    target: MemoryTargetResponse = Field(
        description="Non-secret target coordinates recorded in the catalog."
    )


class RemovedMemoryState(ExpectedMemoryState):
    evidence_bytes: int = Field(
        ge=0, description="Bytes removed from the file-backed evidence store."
    )
    evidence_files: int = Field(
        ge=0, description="Regular files removed from the evidence store."
    )


class MemoryLifecycleResponse(APIModel):
    action: Literal["status", "wipe", "delete"] = Field(
        description="Lifecycle action that completed."
    )
    catalog_entry_removed: bool = Field(
        description="Whether a named memory entry was removed from the catalog."
    )
    memory: str = Field(description="Memory that handled the lifecycle action.")
    removed: RemovedMemoryState | None = Field(
        description="Removed counts for wipe/delete; null for status."
    )
    state: ExpectedMemoryState | None = Field(
        description="Current guard counts for status; null for wipe/delete."
    )
    target: MemoryTargetResponse = Field(
        description="Non-secret coordinates of the affected target."
    )


class MemoryNodeDeleteResponse(NodeDeleteResponse):
    memory: str = Field(description="Memory that handled the deletion.")


class ManagerResponse(APIModel):
    action: str = Field(description="Action executed by the manager tool.")
    memory: str = Field(description="Memory that handled the operation.")
    result: dict[str, Any] = Field(
        description=(
            "Operation result conforming to output_schema in the selected operation "
            "specification."
        )
    )


@dataclass(frozen=True, slots=True)
class OperationDefinition:
    operation: str
    mcp_tool: str
    action: str | None
    request_model: type[BaseModel]
    response_model: type[BaseModel]
    mutating: bool
    destructive: bool
    external_call: bool
    idempotent: bool
    preconditions: tuple[str, ...]
    example_payload: dict[str, Any]
    idempotency: dict[str, Any] | None = None

    @property
    def spec_uri(self) -> str:
        return f"memory://operations/{self.operation}"

    def index_document(self) -> dict[str, Any]:
        document = {
            "call_style": "manager" if self.action is not None else "direct",
            "effects": {
                "destructive": self.destructive,
                "external_call": self.external_call,
                "idempotent": self.idempotent,
                "mutating": self.mutating,
            },
            "mcp_tool": self.mcp_tool,
            "operation": self.operation,
            "spec": self.spec_uri,
        }
        if self.action is not None:
            document["action"] = self.action
        return document

    def document(self, contract_fingerprint: str) -> dict[str, Any]:
        if self.action is None:
            example_call = self.example_payload
        else:
            example_call = {
                "action": self.action,
                "memory": "default",
                "payload": self.example_payload,
            }
        document = {
            **self.index_document(),
            "contract_fingerprint": contract_fingerprint,
            "errors": {
                "registry": "memory://capabilities/current#errors",
                "validation": "invalid_request",
            },
            "example": {"call": example_call},
            "input_schema": self.request_model.model_json_schema(by_alias=True),
            "output_location": "result" if self.action is not None else "tool_result",
            "output_schema": describe_response_schema(
                self.response_model.model_json_schema(by_alias=True)
            ),
            "preconditions": list(self.preconditions),
            "spec_version": "1",
        }
        if self.idempotency is not None:
            document["idempotency"] = self.idempotency
        recovery = []
        if "memory://schema/current" in self.preconditions:
            recovery.append(
                {
                    "code": "schema_changed",
                    "next": "memory://schema/current",
                    "action": "refresh_and_retry_once",
                }
            )
        if self.operation == "memory_lifecycle":
            recovery.append(
                {
                    "code": "memory_state_changed",
                    "next": "memory_lifecycle_manage action=status",
                    "action": "refresh_expected_state",
                }
            )
        if recovery:
            document["recovery"] = recovery
        return document


def _definition(
    operation: str,
    tool: str,
    action: str | None,
    request: type[BaseModel],
    response: type[BaseModel],
    *,
    mutating: bool,
    idempotent: bool,
    example: dict[str, Any],
    preconditions: tuple[str, ...] = ("memory://catalog",),
    destructive: bool = False,
    external_call: bool = False,
    idempotency: dict[str, Any] | None = None,
) -> OperationDefinition:
    return OperationDefinition(
        operation,
        tool,
        action,
        request,
        response,
        mutating,
        destructive,
        external_call,
        idempotent,
        preconditions,
        example,
        idempotency,
    )


_SCHEMA_PRECONDITIONS = ("memory://catalog", "memory://schema/current")
_ONTOLOGY_PRECONDITIONS = ("memory://catalog", "selected-memory ontology")

OPERATION_DEFINITIONS = (
    _definition(
        "memory_configure",
        "memory_configure",
        None,
        ConfigureMemoryRequest,
        MemoryConfigureResponse,
        mutating=True,
        idempotent=False,
        external_call=True,
        example={
            "action": "create",
            "name": "research",
            "backend": "sqlite",
            "database": "/absolute/path/memory.db",
            "evidence_root": "/absolute/path/evidence",
        },
    ),
    _definition(
        "memory_lifecycle",
        "memory_lifecycle_manage",
        None,
        MemoryLifecycleRequest,
        MemoryLifecycleResponse,
        mutating=True,
        destructive=True,
        idempotent=False,
        example={"action": "status", "memory": "default"},
    ),
    _definition(
        "entity_declaration",
        "memory_ontology_manage",
        "declare_entity",
        DeclareEntityRequest,
        OntologyResponse,
        mutating=True,
        idempotent=True,
        preconditions=_SCHEMA_PRECONDITIONS,
        example={
            "entity_type": "example.Session",
            "contract_fingerprint": "<schema_fingerprint>",
            "description": "One interaction session.",
        },
    ),
    _definition(
        "namespace_declaration",
        "memory_ontology_manage",
        "declare_namespace",
        DeclareNamespaceRequest,
        OntologyResponse,
        mutating=True,
        idempotent=True,
        preconditions=_SCHEMA_PRECONDITIONS,
        example={
            "namespace": "example",
            "description": "Example data.",
            "contract_fingerprint": "<schema_fingerprint>",
        },
    ),
    _definition(
        "jsonl_import",
        "memory_ingest_manage",
        "jsonl_import",
        JsonlImportRequest,
        JsonlImportResponse,
        mutating=True,
        idempotent=True,
        preconditions=_SCHEMA_PRECONDITIONS,
        example={
            "source_path": "/absolute/path/records.jsonl",
            "entity_type": "example.Session",
            "key": [{"field": "id", "type": "string"}],
            "contract_fingerprint": "<schema_fingerprint>",
        },
        idempotency={
            "key_source": "server-derived",
            "basis": ["entity_type", "key", "content_hash"],
        },
    ),
    _definition(
        "analytical_attribute_write",
        "memory_ingest_manage",
        "analytical_attribute",
        AnalyticalAttributeRequest,
        AnalyticalAttributeResponse,
        mutating=True,
        idempotent=True,
        preconditions=_SCHEMA_PRECONDITIONS,
        example={
            "node_id": "<node_id>",
            "attribute_name": "classification",
            "value": "excellent",
            "method": "review-v1",
            "contract_fingerprint": "<schema_fingerprint>",
        },
        idempotency={
            "key_source": "server-derived",
            "basis": ["node_id", "attribute_name", "value", "method"],
        },
    ),
    _definition(
        "analytical_metric_write",
        "memory_ingest_manage",
        "analytical_metric",
        AnalyticalMetricRequest,
        AnalyticalMetricResponse,
        mutating=True,
        idempotent=True,
        preconditions=_SCHEMA_PRECONDITIONS,
        example={
            "definition_version": "count-v1",
            "value": 1,
            "dimensions": {"group": "all"},
            "method": "count",
            "method_version": "1",
            "contract_fingerprint": "<schema_fingerprint>",
        },
        idempotency={
            "key_source": "server-derived",
            "basis": [
                "definition_version",
                "value",
                "dimensions",
                "method",
                "method_version",
                "coverage",
                "complete",
                "unit",
                "numerator",
                "denominator",
                "privacy",
            ],
        },
    ),
    _definition(
        "join_materialize",
        "memory_relation_manage",
        "materialize",
        JoinMaterializeRequest,
        JoinMaterializationResponse,
        mutating=True,
        idempotent=False,
        preconditions=_SCHEMA_PRECONDITIONS,
        example={
            "name": "session-message",
            "relation": "example.HAS_MESSAGE",
            "from": {"type": "example.Session", "fields": ["id"]},
            "to": {"type": "example.Message", "fields": ["session_id"]},
            "contract_fingerprint": "<schema_fingerprint>",
        },
        idempotency={
            "key_source": "optional-caller",
            "when_omitted": "server-generated-random",
        },
    ),
    _definition(
        "relation_deactivate",
        "memory_relation_manage",
        "deactivate",
        RelationDeactivateRequest,
        DirectRelationExplanation,
        mutating=True,
        idempotent=True,
        example={"relation_id": "<relation_id>"},
    ),
    _definition(
        "query_execute",
        "memory_query_manage",
        "execute",
        QueryExecuteRequest,
        QueryIRResponse,
        mutating=False,
        idempotent=True,
        preconditions=(
            "memory://catalog",
            "selected-memory ontology",
            "memory://schema/query-ir/current",
        ),
        example={
            "document": {
                "query_ir_version": "1",
                "match": {
                    "nodes": [{"type": "example.Session", "as": "session"}],
                    "edges": [],
                },
                "return": [{"field": "session.status"}],
            }
        },
    ),
    _definition(
        "query_current_metric",
        "memory_query_manage",
        "current_metric",
        CurrentMetricRequest,
        CurrentMetricResponse,
        mutating=False,
        idempotent=True,
        example={"definition_version": "count-v1", "dimensions": {"group": "all"}},
    ),
    _definition(
        "traverse_relations",
        "memory_query_manage",
        "traverse",
        TraverseRelationsRequest,
        TraversalResponse,
        mutating=False,
        idempotent=True,
        preconditions=_ONTOLOGY_PRECONDITIONS,
        example={"start_node_id": "<node_id>", "direction": "outbound"},
    ),
    _definition(
        "search_text",
        "memory_search_manage",
        "text",
        SearchTextRequest,
        SearchResponse,
        mutating=False,
        idempotent=True,
        example={"query": "payment", "limit": 20},
    ),
    _definition(
        "embedding_status",
        "memory_semantic_manage",
        "embedding_status",
        EmbeddingStatusRequest,
        EmbeddingProfileResponse,
        mutating=False,
        idempotent=True,
        external_call=False,
        example={"profile_id": "<profile_id>"},
    ),
    _definition(
        "search_semantic",
        "memory_semantic_manage",
        "search",
        SearchSemanticRequest,
        SemanticSearchResponse,
        mutating=False,
        idempotent=True,
        external_call=True,
        example={"profile_id": "<profile_id>", "query": "payment problem"},
    ),
    _definition(
        "explain_attribute",
        "memory_explain_manage",
        "attribute",
        ExplainAttributeRequest,
        ExplanationResponse,
        mutating=False,
        idempotent=True,
        example={"attribute_id": "<attribute_id>"},
    ),
    _definition(
        "explain_relation",
        "memory_explain_manage",
        "relation",
        ExplainRelationRequest,
        RelationExplanationResponse,
        mutating=False,
        idempotent=True,
        example={"relation_id": "<relation_id>"},
    ),
    _definition(
        "explain_metric",
        "memory_explain_manage",
        "metric",
        ExplainMetricRequest,
        MetricExplanationResponse,
        mutating=False,
        idempotent=True,
        example={"metric_id": "<metric_id>"},
    ),
    _definition(
        "evidence_status",
        "memory_evidence_read_manage",
        "status",
        EvidenceStatusRequest,
        EvidenceStatusResponse,
        mutating=False,
        idempotent=True,
        example={"digest": "<sha256>"},
    ),
    _definition(
        "evidence_read",
        "memory_evidence_read_manage",
        "read",
        EvidenceReadRequest,
        EvidenceReadResponse,
        mutating=False,
        idempotent=True,
        example={"digest": "<sha256>", "offset": 0, "limit": 65536},
    ),
    _definition(
        "evidence_verify",
        "memory_evidence_manage",
        "verify",
        EvidenceVerifyRequest,
        EvidenceVerifyResponse,
        mutating=True,
        idempotent=False,
        example={"digest": "<sha256>"},
    ),
    _definition(
        "evidence_audit",
        "memory_evidence_manage",
        "audit",
        EvidenceAuditRequest,
        EvidenceAuditResponse,
        mutating=True,
        idempotent=False,
        example={"limit": 1000},
    ),
    _definition(
        "delete_node",
        "memory_node_delete",
        None,
        NodeDeleteRequest,
        MemoryNodeDeleteResponse,
        mutating=True,
        destructive=True,
        idempotent=False,
        example={"node_id": "<node_id>", "memory": "default"},
    ),
)

OPERATIONS = {definition.operation: definition for definition in OPERATION_DEFINITIONS}
MCP_ROUTES = {}
for definition in OPERATION_DEFINITIONS:
    route = {"mcp_tool": definition.mcp_tool, "spec": definition.spec_uri}
    if definition.action is not None:
        route["action"] = definition.action
    MCP_ROUTES[definition.operation] = route


def operations_index_document() -> dict[str, Any]:
    return {
        "operations": [
            definition.index_document() for definition in OPERATION_DEFINITIONS
        ],
        "operations_version": "2",
    }


def operation_document(operation: str, contract_fingerprint: str) -> dict[str, Any]:
    try:
        definition = OPERATIONS[operation]
    except KeyError as exc:
        raise ValueError(f"unknown MCP operation {operation!r}") from exc
    return definition.document(contract_fingerprint)
