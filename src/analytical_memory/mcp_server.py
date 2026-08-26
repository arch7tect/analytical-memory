from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from analytical_memory.api import MemoryAPI
from analytical_memory.api_models import (
    ApplyResponse,
    CurrentFactsResponse,
    CurrentMetricResponse,
    CurrentSlotsResponse,
    ExplanationResponse,
    MetricExplanationResponse,
    PreviewResponse,
    RelationExplanationResponse,
    SearchResponse,
    TraversalResponse,
)
from analytical_memory.application import MemoryApplication
from analytical_memory.canonical import canonical_json
from analytical_memory.configuration import build_application
from analytical_memory.errors import MemoryErrorBase


def create_mcp_server(application: MemoryApplication) -> MCPServer:
    api = MemoryAPI(application)
    server = MCPServer(
        "analytical-memory",
        version="0.1.0",
        instructions=(
            "Inspect schema and capabilities resources before calling typed tools. "
            "Raw evidence reads and arbitrary database operations are not exposed."
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
        "memory://schema/ontology/{namespace}",
        name="ontology-namespace",
        description="Namespace metadata for the currently implemented ontology subset.",
        mime_type="application/json",
    )
    def ontology_namespace(namespace: str) -> str:
        return canonical_json(
            {
                "definitions": {},
                "namespace": namespace,
                "schema_fingerprint": application.schema.fingerprint,
                "status": "not_declared",
            }
        )

    @server.tool(
        name="memory_ingest_preview",
        description=(
            "Validate and preview one normalized ingestion batch without writes."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def ingestion_preview(batch_path: str) -> PreviewResponse:
        try:
            return api.ingestion_preview(batch_path)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="memory_ingest_apply",
        description="Validate and atomically apply one normalized ingestion batch.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def ingestion_apply(batch_path: str) -> ApplyResponse:
        try:
            return api.ingestion_apply(batch_path)
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="memory_query_current_facts",
        description="Return the bounded saved current-facts query.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def query_current_facts() -> CurrentFactsResponse:
        try:
            return api.query_current_facts()
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="memory_query_current_slots",
        description="Return complete single- and multi-valued slot semantics.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def query_current_slots() -> CurrentSlotsResponse:
        try:
            return api.query_current_slots()
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

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
            raise ToolError(str(exc)) from exc

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
        states: list[str] | None = None,
    ) -> TraversalResponse:
        try:
            return api.traverse_relations(
                start_node_id,
                relation_types=relation_types,
                direction=direction,
                max_depth=max_depth,
                limit=limit,
                states=states,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

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
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="memory_explain",
        description="Explain one node-attribute fact through assertions and evidence.",
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
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="memory_explain_relation",
        description="Explain one relation fact through assertions and evidence.",
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
            raise ToolError(str(exc)) from exc

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
            raise ToolError(str(exc)) from exc

    return server


def main() -> None:
    create_mcp_server(build_application()).run()


if __name__ == "__main__":
    main()
