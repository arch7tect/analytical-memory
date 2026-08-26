from __future__ import annotations

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from analytical_memory.api import MemoryAPI
from analytical_memory.api_models import (
    ApplyResponse,
    CurrentFactsResponse,
    ExplanationResponse,
    PreviewResponse,
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

    return server


def main() -> None:
    create_mcp_server(build_application()).run()


if __name__ == "__main__":
    main()
