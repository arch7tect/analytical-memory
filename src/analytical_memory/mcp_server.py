from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from analytical_memory.api import MemoryAPI
from analytical_memory.api_models import (
    AnalyticalAttributeResponse,
    AnalyticalMetricResponse,
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
from analytical_memory.application import MemoryApplication
from analytical_memory.canonical import canonical_json
from analytical_memory.configuration import build_application
from analytical_memory.errors import (
    InputOutputError,
    InvalidRequestError,
    MemoryErrorBase,
)
from analytical_memory.query_ir import query_ir_contract_document
from analytical_memory.version import __version__


def _tool_error(exc: MemoryErrorBase | OSError | ValueError) -> ToolError:
    if isinstance(exc, MemoryErrorBase):
        envelope = exc.envelope()
    elif isinstance(exc, OSError):
        envelope = InputOutputError(str(exc)).envelope()
    else:
        envelope = InvalidRequestError(str(exc)).envelope()
    return ToolError(canonical_json(envelope))


def create_mcp_server(application: MemoryApplication) -> MCPServer:
    api = MemoryAPI(application)
    server = MCPServer(
        "analytical-memory",
        version=__version__,
        instructions=(
            "Inspect schema and capabilities resources before calling typed tools. "
            "Raw evidence is available only through the explicit bounded read tool; "
            "arbitrary database operations are not exposed."
        ),
    )

    @server.resource(
        "memory://schema/current",
        name="current-schema",
        description="Current logical schema and saved query contract.",
        mime_type="application/json",
    )
    def current_schema() -> str:
        return canonical_json(application.schema.document)

    @server.resource(
        "memory://capabilities/current",
        name="runtime-capabilities",
        description="Current backend, operations, limits, and retrieval readiness.",
        mime_type="application/json",
    )
    def runtime_capabilities() -> str:
        return canonical_json(application.capabilities())

    @server.resource(
        "memory://schema/queries",
        name="saved-queries",
        description="Saved query names and result contracts.",
        mime_type="application/json",
    )
    def saved_queries() -> str:
        return canonical_json(
            {
                "saved_queries": application.schema.document["saved_queries"],
                "schema_fingerprint": application.schema.fingerprint,
            }
        )

    @server.resource(
        "memory://schema/ontology/current",
        name="current-ontology",
        description="Current data-derived ontology and fingerprint.",
        mime_type="application/json",
    )
    def current_ontology() -> str:
        return canonical_json(application.ontology())

    @server.resource(
        "memory://schema/query-ir/current",
        name="query-ir",
        description="Canonical read-only JSON Query IR v1 contract.",
        mime_type="application/json",
    )
    def query_ir_contract() -> str:
        return canonical_json(
            query_ir_contract_document(application.schema.fingerprint)
        )

    @server.resource(
        "memory://schema/ontology/{namespace}",
        name="ontology-namespace",
        description="Namespace metadata for the currently implemented ontology subset.",
        mime_type="application/json",
    )
    def ontology_namespace(namespace: str) -> str:
        return canonical_json(application.ontology(namespace))

    @server.tool(
        name="memory_ontology_declare_entity",
        description="Create or replace optional entity validation metadata.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def declare_entity(
        entity_type: str,
        contract_fingerprint: str,
        privacy: Literal["public", "private"] = "public",
        fields: dict[str, FieldDeclarationInput] | None = None,
    ) -> OntologyResponse:
        try:
            return api.declare_entity(
                entity_type,
                privacy,
                {
                    name: value.model_dump(mode="json", exclude_none=True)
                    for name, value in (fields or {}).items()
                },
                contract_fingerprint,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_jsonl_import",
        description="Stream, validate, and atomically patch/upsert one JSONL dataset.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def jsonl_import(
        source_path: str,
        entity_type: str,
        key: list[KeyFieldInput],
        contract_fingerprint: str,
    ) -> JsonlImportResponse:
        try:
            return api.jsonl_import(
                source_path,
                entity_type,
                [item.model_dump(mode="json") for item in key],
                contract_fingerprint,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_attribute_write_analysis",
        description=(
            "Write one analytical value as the current attribute with run provenance."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def write_analytical_attribute(
        node_id: str,
        attribute_name: str,
        value: Any,
        method: str,
        contract_fingerprint: str,
    ) -> AnalyticalAttributeResponse:
        try:
            return api.write_analytical_attribute(
                node_id,
                attribute_name,
                value,
                method,
                contract_fingerprint,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_metric_write_analysis",
        description="Write one immutable analytical metric with run provenance.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def write_analytical_metric(
        definition_version: str,
        value: Any,
        dimensions: dict[str, Any],
        method: str,
        method_version: str,
        contract_fingerprint: str,
        coverage: dict[str, Any] | None = None,
        complete: bool = True,
        unit: str | None = None,
        numerator: float | None = None,
        denominator: float | None = None,
        privacy: Literal["public", "private"] = "public",
    ) -> AnalyticalMetricResponse:
        try:
            return api.write_analytical_metric(
                definition_version,
                value,
                dimensions,
                method,
                method_version,
                contract_fingerprint,
                coverage,
                complete,
                unit,
                numerator,
                denominator,
                privacy,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_join_materialize",
        description="Declare and materialize one exact typed join in one transaction.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def materialize_join(
        name: str,
        relation: str,
        from_: JoinEndpointInput,
        to: JoinEndpointInput,
        contract_fingerprint: str,
        idempotency_key: str | None = None,
    ) -> JoinMaterializationResponse:
        try:
            return api.materialize_join(
                name,
                relation,
                from_.model_dump(mode="json"),
                to.model_dump(mode="json"),
                contract_fingerprint,
                idempotency_key,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_query_execute",
        description="Execute one bounded read-only JSON Query IR v1 request.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def execute_query(document: QueryIRDocument) -> QueryIRResponse:
        try:
            query = document.model_dump(
                mode="json", by_alias=True, exclude_unset=True
            )
            return api.execute_query(query)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_relation_deactivate",
        description="Deactivate one current Relation without deleting provenance.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def deactivate_relation(relation_id: str) -> DirectRelationExplanation:
        try:
            return api.deactivate_relation(relation_id)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_node_delete",
        description="Delete one Node and cascade its attributes and Relations.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def delete_node(node_id: str) -> NodeDeleteResponse:
        try:
            return api.delete_node(node_id)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_query_current_metric",
        description="Select the deterministic current metric for an exact scope.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def query_current_metric(
        definition_version: str, dimensions: dict[str, Any]
    ) -> CurrentMetricResponse:
        try:
            return api.query_current_metric(definition_version, dimensions)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_traverse_relations",
        description=(
            "Traverse relation facts with explicit direction, depth, and limits."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def traverse_relations(
        start_node_id: str,
        relation_types: list[str] | None = None,
        direction: Literal["outbound", "inbound", "both"] = "outbound",
        max_depth: int = 3,
        limit: int = 100,
        states: list[Literal["active"]] | None = None,
    ) -> TraversalResponse:
        try:
            return api.traverse_relations(
                start_node_id,
                relation_types=relation_types,
                direction=direction,
                max_depth=max_depth,
                limit=limit,
                states=None if states is None else list(states),
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_search_text",
        description="Search declared text attributes and return facts with provenance.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def search_text(query: str, limit: int = 20) -> SearchResponse:
        try:
            return api.search_text(query, limit)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_embedding_status",
        description="Return local coverage and provider readiness for one profile.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def embedding_status(profile_id: str) -> EmbeddingProfileResponse:
        try:
            return api.embedding_profile_status(profile_id)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_search_semantic",
        description=(
            "Rank locally stored facts by exact cosine similarity. The query text "
            "is sent to the configured commercial embedding API."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        structured_output=True,
    )
    def search_semantic(
        profile_id: str,
        query: str,
        namespace: str | None = None,
        node_type: str | None = None,
        privacy_ceiling: Literal["public"] | None = None,
        limit: int = 20,
    ) -> SemanticSearchResponse:
        try:
            return api.search_semantic(
                profile_id,
                query,
                namespace=namespace,
                node_type=node_type,
                privacy_ceiling=privacy_ceiling,
                limit=limit,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_explain",
        description="Explain one current attribute through its direct provenance.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def explain(attribute_id: str) -> ExplanationResponse:
        try:
            return api.explain(attribute_id)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_explain_relation",
        description="Explain one current relation through its direct provenance.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def explain_relation(relation_id: str) -> RelationExplanationResponse:
        try:
            return api.explain_relation(relation_id)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_explain_metric",
        description="Explain one immutable metric through its run and evidence.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def explain_metric(metric_id: str) -> MetricExplanationResponse:
        try:
            return api.explain_metric(metric_id)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_evidence_status",
        description="Return current provider state for one canonical evidence digest.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def evidence_status(digest: str) -> EvidenceStatusResponse:
        try:
            return api.evidence_status(digest)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_evidence_read",
        description="Read one bounded byte range as base64 without exposing a path.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def evidence_read(
        digest: str, offset: int = 0, limit: int = 65536
    ) -> EvidenceReadResponse:
        try:
            return api.evidence_read(digest, offset=offset, limit=limit)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_evidence_verify",
        description=(
            "Verify one object and its deterministic fragments and append history."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def evidence_verify(digest: str) -> EvidenceVerifyResponse:
        try:
            return api.evidence_verify(digest)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    @server.tool(
        name="memory_evidence_audit",
        description="Boundedly verify canonical evidence and append audit history.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def evidence_audit(limit: int = 1000) -> EvidenceAuditResponse:
        try:
            return api.evidence_audit(limit)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc) from exc

    return server


def main() -> None:
    create_mcp_server(build_application()).run()


if __name__ == "__main__":
    main()
