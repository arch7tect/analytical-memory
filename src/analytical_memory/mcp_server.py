from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError

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
from analytical_memory.configuration import (
    build_application,
    environment_memory_catalog,
)
from analytical_memory.errors import (
    InputOutputError,
    InvalidRequestError,
    MemoryErrorBase,
)
from analytical_memory.mcp_operations import (
    OPERATIONS,
    ManagerResponse,
    MemoryConfigureResponse,
    MemoryNodeDeleteResponse,
    operation_document,
    operations_index_document,
)
from analytical_memory.mcp_schema import DescribedMCPResponse
from analytical_memory.memories import MemoryRouter, contextual_capabilities
from analytical_memory.query_ir import query_ir_contract_document
from analytical_memory.version import __version__

MemorySelection = Annotated[
    str | None,
    Field(
        description=(
            "Configured memory name from memory://catalog. Omit or use 'default' "
            "for the environment-selected default; an explicit unknown name fails."
        )
    ),
]
ContractFingerprint = Annotated[
    str,
    Field(
        description=(
            "Exact schema_fingerprint from memory://schema/current. Refresh that "
            "resource and retry if the server returns schema_changed."
        )
    ),
]
EntityType = Annotated[
    str,
    Field(
        description=(
            "Namespaced entity type such as 'example.Session'; use an existing type "
            "from the selected memory ontology or a new type for import/declaration."
        )
    ),
]
NodeId = Annotated[
    str,
    Field(
        description=(
            "Canonical Node ID obtained from Query IR row bindings, traversal, or "
            "another memory result; it is not the imported business key."
        )
    ),
]
EvidenceDigest = Annotated[
    str,
    Field(
        description=(
            "Lowercase SHA-256 digest returned by import, analytical write, or an "
            "explanation/evidence result in the same memory."
        )
    ),
]
ResolvedMemory = Annotated[
    str,
    Field(
        description=(
            "Memory that actually handled the operation; verify it matches the "
            "requested "
            "name before chaining IDs into another call."
        )
    ),
]
ManagerPayload = Annotated[
    dict[str, Any],
    Field(
        description=(
            "Operation payload. Read the exact schema and example from the operation "
            "URI listed by memory://operations before calling."
        )
    ),
]


def agent_guide_document() -> dict[str, Any]:
    return {
        "guide_version": "1",
        "purpose": (
            "Use Analytical Memory through MCP without database access or source-code "
            "knowledge. Resources describe current data shape; tools perform bounded "
            "typed operations."
        ),
        "selection": {
            "catalog": "memory://catalog",
            "default": (
                "Omit memory on every tool to use the environment-selected default."
            ),
            "named": (
                "Pass the same explicit memory name on every related tool call. There "
                "is no process-wide active selection and no fallback for unknown names."
            ),
            "named_capabilities": ("memory://memories/{memory}/capabilities/current"),
            "named_ontology": ("memory://memories/{memory}/schema/ontology/current"),
        },
        "workflow": [
            {
                "step": 1,
                "action": "Read memory://catalog and choose default or a named memory.",
            },
            {
                "step": 2,
                "action": (
                    "Read capabilities for that memory; confirm storage and evidence "
                    "are initialized and the required operation is enabled. Read "
                    "memory://operations to resolve its manager, action, and spec."
                ),
            },
            {
                "step": 3,
                "action": (
                    "Read the selected operation spec before calling a manager; use "
                    "its exact payload schema and example."
                ),
            },
            {
                "step": 4,
                "action": (
                    "Read the selected memory ontology before imports, joins, "
                    "searches, or queries. Refresh it after any shape-changing write."
                ),
            },
            {
                "step": 5,
                "action": (
                    "Read memory://schema/query-ir/current before action=execute on "
                    "memory_query_manage. Use ontology names exactly."
                ),
            },
            {
                "step": 6,
                "action": (
                    "For writes, pass schema_fingerprint from memory://schema/current; "
                    "this structural contract is shared by all memories."
                ),
            },
        ],
        "operations": {
            "configure": (
                "memory_configure create initializes a new/empty target; attach only "
                "validates an existing target. SQLite needs database and "
                "evidence_root. "
                "PostgreSQL needs connection_env, schema, and evidence_root. Paths are "
                "absolute; connection_env names a per-user .env variable, never a DSN."
            ),
            "import": (
                "memory_ingest_manage action=jsonl_import reads a server-local JSONL "
                "file, one JSON object per line. key is an ordered typed tuple used "
                "to find a current Node; later records patch present fields only."
            ),
            "describe": (
                "memory_ontology_manage declares optional namespace/entity metadata "
                "and validation. Imports may introduce undeclared fields and types."
            ),
            "join": (
                "memory_relation_manage action=materialize explicitly connects Nodes "
                "by equal typed field tuples. from is source and to is target; joins "
                "are never inferred or rerun automatically."
            ),
            "query": (
                "memory_query_manage action=execute is the general relational/graph "
                "read surface. Non-count rows bind aliases to canonical Node IDs."
            ),
            "analysis": (
                "memory_ingest_manage writes analytical attributes and metrics. Use a "
                "Node ID from query bindings; metrics are immutable observations."
            ),
            "provenance": (
                "Search/query results return record/source/run/fragment identifiers. "
                "Use memory_explain_manage for provenance and evidence managers for "
                "bounded raw-byte status, reads, or verification."
            ),
        },
        "results": {
            "common": (
                "Every tool result includes memory. Fingerprints identify the "
                "structural "
                "or ontology contract used. source_id, batch_id, run_id, fragment_id, "
                "and evidence_digest are provenance identities, not business keys."
            ),
            "replay": (
                "replayed=true means the same idempotent operation was already "
                "committed; "
                "returned IDs and counts describe that canonical operation."
            ),
            "import": (
                "records is accepted line count; created_nodes and updated_nodes split "
                "upserts; attributes_written counts present fields; ontology_delta "
                "names "
                "newly observed shape."
            ),
            "join": (
                "created_relations is new active edges. skipped_unmatched and "
                "skipped_null_or_missing explain non-materialized source nodes."
            ),
            "query": (
                "rows contain alias-to-Node-ID bindings and projections with direct "
                "provenance. count is used only for count queries. truncated means "
                "more "
                "rows exist beyond the requested limit."
            ),
            "traversal": (
                "nodes and edges carry depth; truncated means the result limit stopped "
                "the traversal. relation_id can be explained or deactivated."
            ),
            "search": (
                "results contain current target IDs and provenance. coverage reports "
                "eligible versus indexed facts and whether indexing is complete."
            ),
            "evidence": (
                "availability is present or missing; verification is unverified, "
                "verified, "
                "or corrupt. Read data_base64 until eof; audit complete=false or "
                "truncated=true means the requested bound did not cover the catalog."
            ),
        },
        "safety": {
            "privacy": (
                "public is the default. private data is excluded from public export "
                "and "
                "external embedding. Semantic query text is sent to the configured "
                "commercial embedding provider."
            ),
            "destructive": (
                "memory_node_delete cascades current attributes, relations, "
                "embeddings, and search documents but retains immutable "
                "evidence/provenance records."
            ),
            "correction": (
                "memory_relation_deactivate corrects current graph state without "
                "deleting "
                "provenance. Evidence verify/audit append verification history."
            ),
        },
        "errors": (
            "Expected failures are JSON objects with code, message, details, and "
            "retryable. Never silently switch memories after an error."
        ),
    }


class MemoryOntologyResponse(DescribedMCPResponse, OntologyResponse):
    memory: ResolvedMemory


class MemoryJsonlImportResponse(DescribedMCPResponse, JsonlImportResponse):
    memory: ResolvedMemory


class MemoryAnalyticalAttributeResponse(
    DescribedMCPResponse, AnalyticalAttributeResponse
):
    memory: ResolvedMemory


class MemoryAnalyticalMetricResponse(DescribedMCPResponse, AnalyticalMetricResponse):
    memory: ResolvedMemory


class MemoryJoinMaterializationResponse(
    DescribedMCPResponse, JoinMaterializationResponse
):
    memory: ResolvedMemory


class MemoryQueryIRResponse(DescribedMCPResponse, QueryIRResponse):
    memory: ResolvedMemory


class MemoryDirectRelationExplanation(DescribedMCPResponse, DirectRelationExplanation):
    memory: ResolvedMemory


class MemoryCurrentMetricResponse(DescribedMCPResponse, CurrentMetricResponse):
    memory: ResolvedMemory


class MemoryTraversalResponse(DescribedMCPResponse, TraversalResponse):
    memory: ResolvedMemory


class MemorySearchResponse(DescribedMCPResponse, SearchResponse):
    memory: ResolvedMemory


class MemoryEmbeddingProfileResponse(DescribedMCPResponse, EmbeddingProfileResponse):
    memory: ResolvedMemory


class MemorySemanticSearchResponse(DescribedMCPResponse, SemanticSearchResponse):
    memory: ResolvedMemory


class MemoryExplanationResponse(DescribedMCPResponse, ExplanationResponse):
    memory: ResolvedMemory


class MemoryRelationExplanationResponse(
    DescribedMCPResponse, RelationExplanationResponse
):
    memory: ResolvedMemory


class MemoryMetricExplanationResponse(DescribedMCPResponse, MetricExplanationResponse):
    memory: ResolvedMemory


class MemoryEvidenceStatusResponse(DescribedMCPResponse, EvidenceStatusResponse):
    memory: ResolvedMemory


class MemoryEvidenceReadResponse(DescribedMCPResponse, EvidenceReadResponse):
    memory: ResolvedMemory


class MemoryEvidenceVerifyResponse(DescribedMCPResponse, EvidenceVerifyResponse):
    memory: ResolvedMemory


class MemoryEvidenceAuditResponse(DescribedMCPResponse, EvidenceAuditResponse):
    memory: ResolvedMemory


def _error_envelope(
    exc: MemoryErrorBase | OSError | ValueError, memory: str | None = None
) -> dict[str, Any]:
    if isinstance(exc, MemoryErrorBase):
        envelope = exc.envelope()
    elif isinstance(exc, OSError):
        envelope = InputOutputError(str(exc)).envelope()
    else:
        envelope = InvalidRequestError(str(exc)).envelope()
    envelope["details"] = {
        **envelope["details"],
        "memory": "default" if memory is None else memory,
    }
    return envelope


def _tool_error(
    exc: MemoryErrorBase | OSError | ValueError, memory: str | None = None
) -> ToolError:
    return ToolError(canonical_json(_error_envelope(exc, memory)))


def _tag_response[ResponseModel: BaseModel](
    value: BaseModel, memory: str, response_type: type[ResponseModel]
) -> ResponseModel:
    payload = value.model_dump(mode="json", by_alias=True)
    payload["memory"] = memory
    return response_type.model_validate(payload)


def _routed_tool_error(exc: ToolError, operation: str, memory: str | None) -> ToolError:
    definition = OPERATIONS[operation]
    try:
        document = json.loads(str(exc))
    except (json.JSONDecodeError, TypeError, ValueError):
        document = _error_envelope(InvalidRequestError(str(exc)), memory)
    details = document.get("details")
    if not isinstance(details, dict):
        details = {}
    document["details"] = {
        **details,
        "action": definition.action,
        "mcp_tool": definition.mcp_tool,
        "memory": "default" if memory is None else memory,
        "spec": definition.spec_uri,
    }
    return ToolError(canonical_json(document))


def _invoke_managed(
    operation: str,
    payload: dict[str, Any],
    memory: str | None,
    handler: Callable[[Any], BaseModel],
) -> ManagerResponse:
    definition = OPERATIONS[operation]
    try:
        request = definition.request_model.model_validate(payload)
    except ValidationError as exc:
        error = InvalidRequestError(
            "manager payload does not match the operation specification",
            details={
                "action": definition.action,
                "errors": exc.errors(include_url=False),
                "mcp_tool": definition.mcp_tool,
                "spec": definition.spec_uri,
            },
        )
        raise _tool_error(error, memory) from exc
    try:
        response = handler(request)
    except ToolError as exc:
        raise _routed_tool_error(exc, operation, memory) from exc
    result = response.model_dump(mode="json", by_alias=True)
    selected = result.pop("memory", "default" if memory is None else memory)
    if definition.action is None:
        raise RuntimeError(f"direct operation {operation!r} cannot use a manager")
    return ManagerResponse(
        action=definition.action,
        memory=selected,
        result=result,
    )


def _internal_handler(
    **_: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        return function

    return decorator


def create_mcp_server(
    application: MemoryApplication, router: MemoryRouter | None = None
) -> MCPServer:
    memory_router = router or MemoryRouter(application, environment_memory_catalog())

    def selected_api(memory: str | None) -> tuple[str, MemoryAPI]:
        selected, selected_application = memory_router.resolve(memory)
        return selected, MemoryAPI(selected_application)

    def capabilities(memory: str | None) -> dict[str, Any]:
        selected, selected_application = memory_router.resolve(memory)
        return contextual_capabilities(selected_application, selected)

    def resource_document(memory: str | None, operation: Any) -> str:
        try:
            return canonical_json(operation())
        except (MemoryErrorBase, OSError, ValueError) as exc:
            return canonical_json(_error_envelope(exc, memory))

    server = MCPServer(
        "analytical-memory",
        version=__version__,
        instructions=(
            "Start with memory://guide, memory://catalog, then memory://operations. "
            "Omit the optional "
            "memory argument for default or pass one catalog name consistently; there "
            "is no active selection. Read the exact operation spec, capabilities, and "
            "ontology for that memory. Read Query IR before general queries. Writes "
            "require schema_fingerprint from memory://schema/current. Refresh ontology "
            "after imports, declarations, or joins. Raw evidence is available only "
            "through bounded evidence tools; arbitrary database operations are not "
            "exposed."
        ),
    )

    @server.resource(
        "memory://guide",
        name="agent-guide",
        description=(
            "Start here: complete source-code-independent workflow for selecting, "
            "discovering, writing, querying, and explaining a memory."
        ),
        mime_type="application/json",
    )
    def agent_guide() -> str:
        return canonical_json(agent_guide_document())

    @server.resource(
        "memory://schema/current",
        name="current-schema",
        description=(
            "Shared structural contract for every memory. Read schema_fingerprint here "
            "and pass it unchanged to mutating tools; this is not the data ontology."
        ),
        mime_type="application/json",
    )
    def current_schema() -> str:
        return canonical_json(application.schema.document)

    @server.resource(
        "memory://capabilities/current",
        name="runtime-capabilities",
        description=(
            "Default-memory readiness, enabled operations, limits, retrieval "
            "providers, "
            "errors, and discovery links. Use the named template for another memory."
        ),
        mime_type="application/json",
    )
    def runtime_capabilities() -> str:
        return canonical_json(capabilities(None))

    @server.resource(
        "memory://schema/queries",
        name="saved-queries",
        description=(
            "Convenience query parameters and result summaries. For general relational "
            "or graph queries, use memory://schema/query-ir/current instead."
        ),
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
        description=(
            "Default-memory entity types, fields, descriptions, relations, privacy, "
            "and "
            "statistics. Refresh after imports, declarations, or joins."
        ),
        mime_type="application/json",
    )
    def current_ontology() -> str:
        return resource_document(
            None, lambda: {**application.ontology(), "memory": "default"}
        )

    @server.resource(
        "memory://schema/query-ir/current",
        name="query-ir",
        description=(
            "Authoritative Query IR v1 input/result JSON Schemas, semantics, limits, "
            "and examples for memory_query_manage action=execute."
        ),
        mime_type="application/json",
    )
    def query_ir_contract() -> str:
        return canonical_json(
            query_ir_contract_document(application.schema.fingerprint)
        )

    @server.resource(
        "memory://operations",
        name="operation-index",
        description=(
            "Concrete index of callable MCP operations, manager/action routing, "
            "effects, and links to exact lazy specifications."
        ),
        mime_type="application/json",
    )
    def operation_index() -> str:
        return canonical_json(operations_index_document())

    @server.resource(
        "memory://operations/{operation}",
        name="operation-specification",
        description=(
            "Exact payload and result schemas, effects, preconditions, errors, and "
            "example for one operation named by memory://operations."
        ),
        mime_type="application/json",
    )
    def operation_specification(operation: str) -> str:
        return resource_document(
            None,
            lambda: operation_document(operation, application.schema.fingerprint),
        )

    @server.resource(
        "memory://schema/ontology/{namespace}",
        name="ontology-namespace",
        description=(
            "Default-memory ontology filtered to one namespace name learned from the "
            "current ontology. Use the named template for another memory."
        ),
        mime_type="application/json",
    )
    def ontology_namespace(namespace: str) -> str:
        return resource_document(
            None,
            lambda: {**application.ontology(namespace), "memory": "default"},
        )

    @server.resource(
        "memory://catalog",
        name="memory-catalog",
        description=(
            "Available memory names and non-secret targets. Omit memory for default; "
            "reading this resource never changes an active selection."
        ),
        mime_type="application/json",
    )
    def memory_catalog() -> str:
        return resource_document(None, memory_router.catalog)

    @server.resource(
        "memory://memories/{memory}/capabilities/current",
        name="named-runtime-capabilities",
        description=(
            "Readiness, enabled operations, limits, retrieval providers, errors, and "
            "discovery links for an explicit name from memory://catalog."
        ),
        mime_type="application/json",
    )
    def named_runtime_capabilities(memory: str) -> str:
        return resource_document(memory, lambda: capabilities(memory))

    @server.resource(
        "memory://memories/{memory}/schema/ontology/current",
        name="named-current-ontology",
        description=(
            "Entity types, fields, descriptions, relations, privacy, and statistics "
            "for "
            "an explicit memory name. Refresh after imports, declarations, or joins."
        ),
        mime_type="application/json",
    )
    def named_current_ontology(memory: str) -> str:
        def document() -> dict[str, Any]:
            selected, selected_application = memory_router.resolve(memory)
            return {**selected_application.ontology(), "memory": selected}

        return resource_document(memory, document)

    @server.resource(
        "memory://memories/{memory}/schema/ontology/{namespace}",
        name="named-ontology-namespace",
        description=(
            "Ontology for one namespace in an explicit memory. Learn both memory and "
            "namespace names from the catalog and current named ontology first."
        ),
        mime_type="application/json",
    )
    def named_ontology_namespace(memory: str, namespace: str) -> str:
        def document() -> dict[str, Any]:
            selected, selected_application = memory_router.resolve(memory)
            return {**selected_application.ontology(namespace), "memory": selected}

        return resource_document(memory, document)

    @server.tool(
        name="memory_configure",
        description=(
            "Create a new/empty named memory or read-only attach an existing "
            "compatible "
            "one. This records only non-secret target coordinates; it does not select "
            "the memory for later calls."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        ),
        structured_output=True,
    )
    def configure_memory(
        action: Annotated[
            Literal["create", "attach"],
            Field(
                description=(
                    "create initializes a new/empty target; attach only validates an "
                    "already initialized target and never migrates or repairs it."
                )
            ),
        ],
        name: Annotated[
            str,
            Field(
                description=(
                    "New lowercase catalog alias. 'default' is reserved; configuring a "
                    "name that already exists fails."
                )
            ),
        ],
        backend: Annotated[
            Literal["sqlite", "postgresql"],
            Field(description="Storage backend used by this named memory."),
        ],
        evidence_root: Annotated[
            str,
            Field(
                description=(
                    "Absolute path to this memory's local evidence directory. It must "
                    "not equal, contain, or be contained by another evidence root."
                )
            ),
        ],
        database: Annotated[
            str | None,
            Field(
                description=(
                    "Absolute SQLite database path. Required only for backend=sqlite; "
                    "omit for PostgreSQL."
                )
            ),
        ] = None,
        connection_env: Annotated[
            str | None,
            Field(
                description=(
                    "Name of a per-user environment variable containing the PostgreSQL "
                    "URL. Required only for PostgreSQL; never pass the URL itself."
                )
            ),
        ] = None,
        schema: Annotated[
            str | None,
            Field(
                description=(
                    "PostgreSQL schema dedicated to this memory. Required only for "
                    "backend=postgresql; omit for SQLite."
                )
            ),
        ] = None,
    ) -> MemoryConfigureResponse:
        try:
            return MemoryConfigureResponse.model_validate(
                memory_router.configure(
                    action=action,
                    name=name,
                    backend=backend,
                    evidence_root=evidence_root,
                    database=database,
                    connection_env=connection_env,
                    postgres_schema=schema,
                )
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, name) from exc

    @_internal_handler(
        name="memory_ontology_declare_entity",
        description=(
            "Create or replace optional descriptions, privacy, and field validation "
            "metadata for one entity type. Undeclared fields may still be imported."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def declare_entity(
        entity_type: EntityType,
        contract_fingerprint: ContractFingerprint,
        description: Annotated[
            str | None,
            Field(
                description=(
                    "Optional human-readable meaning of the entity type; omit to clear "
                    "an existing description."
                )
            ),
        ] = None,
        privacy: Annotated[
            Literal["public", "private"],
            Field(
                description=(
                    "Default privacy for this entity. private excludes its data from "
                    "public export and external embedding."
                )
            ),
        ] = "public",
        fields: Annotated[
            dict[str, FieldDeclarationInput] | None,
            Field(
                description=(
                    "Optional map from attribute name to declaration metadata. The map "
                    "replaces the prior declaration; omit for no declared fields."
                )
            ),
        ] = None,
        memory: MemorySelection = None,
    ) -> MemoryOntologyResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.declare_entity(
                    entity_type,
                    privacy,
                    {
                        name: value.model_dump(mode="json", exclude_none=True)
                        for name, value in (fields or {}).items()
                    },
                    contract_fingerprint,
                    description,
                ),
                selected,
                MemoryOntologyResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_ontology_declare_namespace",
        description=(
            "Create or replace the human-readable description of one namespace used by "
            "entity types in the selected memory."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def declare_namespace(
        namespace: Annotated[
            str,
            Field(
                description=(
                    "Namespace prefix before the dot in entity types, for example "
                    "'example' in 'example.Session'."
                )
            ),
        ],
        description: Annotated[
            str,
            Field(description="Non-empty human-readable meaning of the namespace."),
        ],
        contract_fingerprint: ContractFingerprint,
        memory: MemorySelection = None,
    ) -> MemoryOntologyResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.declare_namespace(namespace, description, contract_fingerprint),
                selected,
                MemoryOntologyResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_jsonl_import",
        description=(
            "Stream one server-local JSONL file and atomically patch/upsert nodes of "
            "one "
            "entity type. Refresh ontology after success before planning queries."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def jsonl_import(
        source_path: Annotated[
            str,
            Field(
                description=(
                    "Path visible to the MCP server, not client file bytes. The UTF-8 "
                    "JSONL file must contain exactly one JSON object per non-empty "
                    "line."
                )
            ),
        ],
        entity_type: EntityType,
        key: Annotated[
            list[KeyFieldInput],
            Field(
                description=(
                    "Ordered non-empty fields and scalar types used together to find "
                    "an existing node during this import. Keys are not persisted "
                    "identities."
                )
            ),
        ],
        contract_fingerprint: ContractFingerprint,
        memory: MemorySelection = None,
    ) -> MemoryJsonlImportResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.jsonl_import(
                    source_path,
                    entity_type,
                    [item.model_dump(mode="json") for item in key],
                    contract_fingerprint,
                ),
                selected,
                MemoryJsonlImportResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_attribute_write_analysis",
        description=(
            "Write or replace one current analytical attribute on an existing Node, "
            "recording method, run, source, and evidence provenance."
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
        node_id: NodeId,
        attribute_name: Annotated[
            str,
            Field(
                description=(
                    "Attribute name to create or replace on the Node, such as "
                    "'classification'. It becomes part of the current ontology."
                )
            ),
        ],
        value: Annotated[
            Any,
            Field(
                description=(
                    "JSON value for the current analytical attribute: null, string, "
                    "number, boolean, object, or array."
                )
            ),
        ],
        method: Annotated[
            str,
            Field(
                description=(
                    "Stable identifier for the analysis procedure that produced the "
                    "value, including a version when behavior may change."
                )
            ),
        ],
        contract_fingerprint: ContractFingerprint,
        memory: MemorySelection = None,
    ) -> MemoryAnalyticalAttributeResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.write_analytical_attribute(
                    node_id,
                    attribute_name,
                    value,
                    method,
                    contract_fingerprint,
                ),
                selected,
                MemoryAnalyticalAttributeResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_metric_write_analysis",
        description=(
            "Append one immutable analytical metric observation with exact dimensions, "
            "coverage, method version, run, source, and evidence provenance."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def write_analytical_metric(
        definition_version: Annotated[
            str,
            Field(
                description=(
                    "Stable metric definition identifier including its semantic "
                    "version, "
                    "for example 'failed-rate-v1'."
                )
            ),
        ],
        value: Annotated[
            Any,
            Field(description="JSON metric value produced by this analytical run."),
        ],
        dimensions: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "Exact JSON scope of the observation. Current-metric lookup must "
                    "use "
                    "the same definition_version and dimensions."
                )
            ),
        ],
        method: Annotated[
            str,
            Field(description="Stable name of the analysis procedure."),
        ],
        method_version: Annotated[
            str,
            Field(description="Version of the analysis procedure implementation."),
        ],
        contract_fingerprint: ContractFingerprint,
        coverage: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "Optional JSON summary of included/excluded records, time "
                    "interval, "
                    "or other coverage needed to interpret the observation."
                )
            ),
        ] = None,
        complete: Annotated[
            bool,
            Field(
                description=(
                    "Whether the observation completely covers its declared scope."
                )
            ),
        ] = True,
        unit: Annotated[
            str | None,
            Field(description="Optional unit label, such as 'calls' or 'percent'."),
        ] = None,
        numerator: Annotated[
            float | None,
            Field(description="Optional numerator used to derive a ratio value."),
        ] = None,
        denominator: Annotated[
            float | None,
            Field(description="Optional denominator used to derive a ratio value."),
        ] = None,
        privacy: Annotated[
            Literal["public", "private"],
            Field(description="Privacy class of this metric observation."),
        ] = "public",
        memory: MemorySelection = None,
    ) -> MemoryAnalyticalMetricResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.write_analytical_metric(
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
                ),
                selected,
                MemoryAnalyticalMetricResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_join_materialize",
        description=(
            "Declare and materialize a directed relation between already imported "
            "entity "
            "types by exact equality of ordered typed field tuples, in one transaction."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def materialize_join(
        name: Annotated[
            str,
            Field(
                description=(
                    "Stable logical join declaration name, unique within the memory."
                )
            ),
        ],
        relation: Annotated[
            str,
            Field(
                description=(
                    "Relation type written on matching edges and later used in Query "
                    "IR "
                    "edge patterns or traversal filters."
                )
            ),
        ],
        from_: Annotated[
            JoinEndpointInput,
            Field(
                description=(
                    "Directed source endpoint: entity type and ordered fields whose "
                    "tuple is matched to the to endpoint."
                )
            ),
        ],
        to: Annotated[
            JoinEndpointInput,
            Field(
                description=(
                    "Directed target endpoint: entity type and ordered fields matched "
                    "positionally to from_.fields."
                )
            ),
        ],
        contract_fingerprint: ContractFingerprint,
        idempotency_key: Annotated[
            str | None,
            Field(
                description=(
                    "Optional caller-stable replay key. Reusing it with different "
                    "input "
                    "is an idempotency conflict."
                )
            ),
        ] = None,
        description: Annotated[
            str | None,
            Field(description="Optional human-readable meaning of the relation."),
        ] = None,
        memory: MemorySelection = None,
    ) -> MemoryJoinMaterializationResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.materialize_join(
                    name,
                    relation,
                    from_.model_dump(mode="json"),
                    to.model_dump(mode="json"),
                    contract_fingerprint,
                    idempotency_key,
                    description,
                ),
                selected,
                MemoryJoinMaterializationResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_query_execute",
        description=(
            "Execute one bounded read-only Query IR v1 relational/graph request. Read "
            "the selected ontology and memory://schema/query-ir/current first."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def execute_query(
        document: Annotated[
            QueryIRDocument,
            Field(
                description=(
                    "Query IR v1 document. Entity, attribute, and relation names must "
                    "come from the selected ontology; exact syntax and examples are in "
                    "memory://schema/query-ir/current."
                )
            ),
        ],
        memory: MemorySelection = None,
    ) -> MemoryQueryIRResponse:
        try:
            selected, api = selected_api(memory)
            query = document.model_dump(mode="json", by_alias=True, exclude_unset=True)
            return _tag_response(
                api.execute_query(query), selected, MemoryQueryIRResponse
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_relation_deactivate",
        description=(
            "Deactivate one current relation edge as an explicit correction while "
            "retaining its source, run, evidence, and explanation history."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def deactivate_relation(
        relation_id: Annotated[
            str,
            Field(
                description=(
                    "Canonical relation_id obtained from traversal, a Query IR "
                    "relation "
                    "result, join output follow-up, or memory_explain_relation."
                )
            ),
        ],
        memory: MemorySelection = None,
    ) -> MemoryDirectRelationExplanation:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.deactivate_relation(relation_id),
                selected,
                MemoryDirectRelationExplanation,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @server.tool(
        name="memory_node_delete",
        description=(
            "Delete one current Node and cascade its current attributes, relation "
            "edges, "
            "embeddings, and search documents. Immutable evidence remains retained."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def delete_node(
        node_id: NodeId,
        memory: MemorySelection = None,
    ) -> MemoryNodeDeleteResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.delete_node(node_id), selected, MemoryNodeDeleteResponse
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_query_current_metric",
        description=(
            "Select the deterministic current immutable metric observation for one "
            "exact "
            "definition version and dimensions scope."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def query_current_metric(
        definition_version: Annotated[
            str,
            Field(description="Exact metric definition_version used when writing."),
        ],
        dimensions: Annotated[
            dict[str, Any],
            Field(description="Exact dimensions JSON object used when writing."),
        ],
        memory: MemorySelection = None,
    ) -> MemoryCurrentMetricResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.query_current_metric(definition_version, dimensions),
                selected,
                MemoryCurrentMetricResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_traverse_relations",
        description=(
            "Traverse active relation edges from one canonical Node with explicit "
            "direction, relation filters, depth, and result bounds."
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
        start_node_id: NodeId,
        relation_types: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Optional relation type names from the selected ontology. Omit to "
                    "traverse every active relation type."
                )
            ),
        ] = None,
        direction: Annotated[
            Literal["outbound", "inbound", "both"],
            Field(
                description=(
                    "Edge direction relative to start_node_id: source-to-target, "
                    "target-to-source, or both."
                )
            ),
        ] = "outbound",
        max_depth: Annotated[
            int,
            Field(description="Maximum graph hops, bounded by capabilities.limits."),
        ] = 3,
        limit: Annotated[
            int,
            Field(
                description=(
                    "Maximum returned traversal items, bounded by capabilities.limits."
                )
            ),
        ] = 100,
        states: Annotated[
            list[Literal["active"]] | None,
            Field(
                description=(
                    "Optional relation lifecycle filter. V1 supports only ['active']; "
                    "omit for active relations."
                )
            ),
        ] = None,
        memory: MemorySelection = None,
    ) -> MemoryTraversalResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.traverse_relations(
                    start_node_id,
                    relation_types=relation_types,
                    direction=direction,
                    max_depth=max_depth,
                    limit=limit,
                    states=None if states is None else list(states),
                ),
                selected,
                MemoryTraversalResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_search_text",
        description=(
            "Full-text search current public searchable string attributes in the "
            "selected memory and return direct provenance and coverage."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def search_text(
        query: Annotated[
            str,
            Field(description="Non-empty words or numbers to search for locally."),
        ],
        limit: Annotated[
            int,
            Field(
                description="Maximum matches, bounded by capabilities search_results."
            ),
        ] = 20,
        memory: MemorySelection = None,
    ) -> MemorySearchResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.search_text(query, limit), selected, MemorySearchResponse
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_embedding_status",
        description=(
            "Return stored-vector coverage and configured commercial-provider "
            "readiness "
            "for one embedding profile. Profile creation/rebuild is CLI-only."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def embedding_status(
        profile_id: Annotated[
            str,
            Field(
                description=(
                    "Embedding profile ID returned by CLI profile creation or a prior "
                    "embedding status/search result in this memory."
                )
            ),
        ],
        memory: MemorySelection = None,
    ) -> MemoryEmbeddingProfileResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.embedding_profile_status(profile_id),
                selected,
                MemoryEmbeddingProfileResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_search_semantic",
        description=(
            "Embed query text with the configured commercial API, then rank stored "
            "public facts locally by exact cosine similarity."
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
        profile_id: Annotated[
            str,
            Field(description="Ready embedding profile ID in the selected memory."),
        ],
        query: Annotated[
            str,
            Field(
                description=(
                    "Natural-language query sent to the configured commercial "
                    "embedding "
                    "provider; do not include private or secret content."
                )
            ),
        ],
        namespace: Annotated[
            str | None,
            Field(
                description=(
                    "Optional exact namespace filter from the selected ontology."
                )
            ),
        ] = None,
        node_type: Annotated[
            str | None,
            Field(description="Optional exact entity type filter from the ontology."),
        ] = None,
        privacy_ceiling: Annotated[
            Literal["public"] | None,
            Field(
                description=(
                    "Optional explicit privacy ceiling. Only public is supported and "
                    "public is enforced even when omitted."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                description="Maximum matches, bounded by capabilities search_results."
            ),
        ] = 20,
        memory: MemorySelection = None,
    ) -> MemorySemanticSearchResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.search_semantic(
                    profile_id,
                    query,
                    namespace=namespace,
                    node_type=node_type,
                    privacy_ceiling=privacy_ceiling,
                    limit=limit,
                ),
                selected,
                MemorySemanticSearchResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_explain",
        description=(
            "Explain one current NodeAttribute value through its Node, source, "
            "evidence "
            "status, batch/run identifiers, and structural schema fingerprint."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def explain(
        attribute_id: Annotated[
            str,
            Field(
                description=(
                    "Current attribute record ID returned by query projection "
                    "record_id, "
                    "text/semantic search target_id, or an analytical attribute write."
                )
            ),
        ],
        memory: MemorySelection = None,
    ) -> MemoryExplanationResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.explain(attribute_id), selected, MemoryExplanationResponse
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_explain_relation",
        description=(
            "Explain one current relation edge through its endpoints, source, evidence "
            "status, batch/run identifiers, and structural schema fingerprint."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def explain_relation(
        relation_id: Annotated[
            str,
            Field(
                description=(
                    "Canonical relation_id returned by traversal or a prior relation "
                    "result in the selected memory."
                )
            ),
        ],
        memory: MemorySelection = None,
    ) -> MemoryRelationExplanationResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.explain_relation(relation_id),
                selected,
                MemoryRelationExplanationResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_explain_metric",
        description=(
            "Explain one immutable metric observation through its definition, scope, "
            "coverage, analytical run, source, and direct evidence status."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def explain_metric(
        metric_id: Annotated[
            str,
            Field(
                description=(
                    "Canonical metric_id returned by analytical metric write or "
                    "current "
                    "metric query in the selected memory."
                )
            ),
        ],
        memory: MemorySelection = None,
    ) -> MemoryMetricExplanationResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.explain_metric(metric_id),
                selected,
                MemoryMetricExplanationResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_evidence_status",
        description=(
            "Return availability, verification, size, effective privacy, and "
            "retirement "
            "state for one content-addressed evidence object without reading bytes."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def evidence_status(
        digest: EvidenceDigest,
        memory: MemorySelection = None,
    ) -> MemoryEvidenceStatusResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.evidence_status(digest), selected, MemoryEvidenceStatusResponse
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_evidence_read",
        description=(
            "Read one bounded byte range from a present evidence object as base64. Use "
            "status first and continue with offset until eof when more bytes are "
            "needed."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def evidence_read(
        digest: EvidenceDigest,
        offset: Annotated[
            int,
            Field(description="Zero-based byte offset within the evidence object."),
        ] = 0,
        limit: Annotated[
            int,
            Field(
                description=(
                    "Maximum bytes to return in this call, bounded by capabilities raw "
                    "read max_bytes."
                )
            ),
        ] = 65536,
        memory: MemorySelection = None,
    ) -> MemoryEvidenceReadResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.evidence_read(digest, offset=offset, limit=limit),
                selected,
                MemoryEvidenceReadResponse,
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_evidence_verify",
        description=(
            "Hash-verify one evidence object and its deterministic fragments against "
            "canonical digests, then append a verification-history record."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def evidence_verify(
        digest: EvidenceDigest,
        memory: MemorySelection = None,
    ) -> MemoryEvidenceVerifyResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.evidence_verify(digest), selected, MemoryEvidenceVerifyResponse
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @_internal_handler(
        name="memory_evidence_audit",
        description=(
            "Boundedly verify canonical evidence objects, report "
            "missing/corrupt/orphan "
            "state, and append verification history. This never deletes evidence."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def evidence_audit(
        limit: Annotated[
            int,
            Field(
                description=(
                    "Maximum catalog objects to inspect, bounded by capabilities "
                    "validated_evidence_objects. Check complete/truncated in the "
                    "result."
                )
            ),
        ] = 1000,
        memory: MemorySelection = None,
    ) -> MemoryEvidenceAuditResponse:
        try:
            selected, api = selected_api(memory)
            return _tag_response(
                api.evidence_audit(limit), selected, MemoryEvidenceAuditResponse
            )
        except (MemoryErrorBase, OSError, ValueError) as exc:
            raise _tool_error(exc, memory) from exc

    @server.tool(
        name="memory_ontology_manage",
        description=(
            "Manage ontology declarations. Actions: declare_entity, "
            "declare_namespace. Read memory://operations first for exact payloads."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def manage_ontology(
        action: Annotated[
            Literal["declare_entity", "declare_namespace"],
            Field(description="Ontology action selected from memory://operations."),
        ],
        payload: ManagerPayload,
        memory: MemorySelection = None,
    ) -> ManagerResponse:
        if action == "declare_entity":
            return _invoke_managed(
                "entity_declaration",
                payload,
                memory,
                lambda request: declare_entity(
                    request.entity_type,
                    request.contract_fingerprint,
                    request.description,
                    request.privacy,
                    request.fields,
                    memory,
                ),
            )
        if action == "declare_namespace":
            return _invoke_managed(
                "namespace_declaration",
                payload,
                memory,
                lambda request: declare_namespace(
                    request.namespace,
                    request.description,
                    request.contract_fingerprint,
                    memory,
                ),
            )
        raise RuntimeError(f"unhandled ontology action {action!r}")

    @server.tool(
        name="memory_ingest_manage",
        description=(
            "Ingest source or analytical information. Actions: jsonl_import, "
            "analytical_attribute, analytical_metric. Read memory://operations first."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def manage_ingest(
        action: Annotated[
            Literal["jsonl_import", "analytical_attribute", "analytical_metric"],
            Field(description="Ingestion action selected from memory://operations."),
        ],
        payload: ManagerPayload,
        memory: MemorySelection = None,
    ) -> ManagerResponse:
        if action == "jsonl_import":
            return _invoke_managed(
                "jsonl_import",
                payload,
                memory,
                lambda request: jsonl_import(
                    request.source_path,
                    request.entity_type,
                    request.key,
                    request.contract_fingerprint,
                    memory,
                ),
            )
        if action == "analytical_attribute":
            return _invoke_managed(
                "analytical_attribute_write",
                payload,
                memory,
                lambda request: write_analytical_attribute(
                    request.node_id,
                    request.attribute_name,
                    request.value,
                    request.method,
                    request.contract_fingerprint,
                    memory,
                ),
            )
        if action == "analytical_metric":
            return _invoke_managed(
                "analytical_metric_write",
                payload,
                memory,
                lambda request: write_analytical_metric(
                    request.definition_version,
                    request.value,
                    request.dimensions,
                    request.method,
                    request.method_version,
                    request.contract_fingerprint,
                    request.coverage,
                    request.complete,
                    request.unit,
                    request.numerator,
                    request.denominator,
                    request.privacy,
                    memory,
                ),
            )
        raise RuntimeError(f"unhandled ingestion action {action!r}")

    @server.tool(
        name="memory_relation_manage",
        description=(
            "Manage current directed relations. Actions: materialize, deactivate. "
            "Read memory://operations first for exact payloads."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def manage_relation(
        action: Annotated[
            Literal["materialize", "deactivate"],
            Field(description="Relation action selected from memory://operations."),
        ],
        payload: ManagerPayload,
        memory: MemorySelection = None,
    ) -> ManagerResponse:
        if action == "materialize":
            return _invoke_managed(
                "join_materialize",
                payload,
                memory,
                lambda request: materialize_join(
                    request.name,
                    request.relation,
                    request.from_,
                    request.to,
                    request.contract_fingerprint,
                    request.idempotency_key,
                    request.description,
                    memory,
                ),
            )
        if action == "deactivate":
            return _invoke_managed(
                "relation_deactivate",
                payload,
                memory,
                lambda request: deactivate_relation(request.relation_id, memory),
            )
        raise RuntimeError(f"unhandled relation action {action!r}")

    @server.tool(
        name="memory_query_manage",
        description=(
            "Run bounded local reads. Actions: execute, current_metric, traverse. "
            "Read memory://operations first for exact payloads."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def manage_query(
        action: Annotated[
            Literal["execute", "current_metric", "traverse"],
            Field(description="Query action selected from memory://operations."),
        ],
        payload: ManagerPayload,
        memory: MemorySelection = None,
    ) -> ManagerResponse:
        if action == "execute":
            return _invoke_managed(
                "query_execute",
                payload,
                memory,
                lambda request: execute_query(request.document, memory),
            )
        if action == "current_metric":
            return _invoke_managed(
                "query_current_metric",
                payload,
                memory,
                lambda request: query_current_metric(
                    request.definition_version, request.dimensions, memory
                ),
            )
        if action == "traverse":
            return _invoke_managed(
                "traverse_relations",
                payload,
                memory,
                lambda request: traverse_relations(
                    request.start_node_id,
                    request.relation_types,
                    request.direction,
                    request.max_depth,
                    request.limit,
                    request.states,
                    memory,
                ),
            )
        raise RuntimeError(f"unhandled query action {action!r}")

    @server.tool(
        name="memory_search_manage",
        description=(
            "Search current public text locally. Action: text. Read "
            "memory://operations/search_text for the exact payload."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def manage_search(
        action: Annotated[
            Literal["text"], Field(description="Local search action; must be text.")
        ],
        payload: ManagerPayload,
        memory: MemorySelection = None,
    ) -> ManagerResponse:
        return _invoke_managed(
            "search_text",
            payload,
            memory,
            lambda request: search_text(request.query, request.limit, memory),
        )

    @server.tool(
        name="memory_semantic_manage",
        description=(
            "Manage semantic retrieval. Actions: search, embedding_status. The search "
            "action sends public query text to the configured external provider."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
        structured_output=True,
    )
    def manage_semantic(
        action: Annotated[
            Literal["search", "embedding_status"],
            Field(description="Semantic action selected from memory://operations."),
        ],
        payload: ManagerPayload,
        memory: MemorySelection = None,
    ) -> ManagerResponse:
        if action == "embedding_status":
            return _invoke_managed(
                "embedding_status",
                payload,
                memory,
                lambda request: embedding_status(request.profile_id, memory),
            )
        if action == "search":
            return _invoke_managed(
                "search_semantic",
                payload,
                memory,
                lambda request: search_semantic(
                    request.profile_id,
                    request.query,
                    request.namespace,
                    request.node_type,
                    request.privacy_ceiling,
                    request.limit,
                    memory,
                ),
            )
        raise RuntimeError(f"unhandled semantic action {action!r}")

    @server.tool(
        name="memory_explain_manage",
        description=(
            "Explain direct provenance. Actions: attribute, relation, metric. Read "
            "memory://operations first for exact payloads."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def manage_explain(
        action: Annotated[
            Literal["attribute", "relation", "metric"],
            Field(description="Explanation action selected from memory://operations."),
        ],
        payload: ManagerPayload,
        memory: MemorySelection = None,
    ) -> ManagerResponse:
        if action == "attribute":
            return _invoke_managed(
                "explain_attribute",
                payload,
                memory,
                lambda request: explain(request.attribute_id, memory),
            )
        if action == "relation":
            return _invoke_managed(
                "explain_relation",
                payload,
                memory,
                lambda request: explain_relation(request.relation_id, memory),
            )
        if action == "metric":
            return _invoke_managed(
                "explain_metric",
                payload,
                memory,
                lambda request: explain_metric(request.metric_id, memory),
            )
        raise RuntimeError(f"unhandled explanation action {action!r}")

    @server.tool(
        name="memory_evidence_read_manage",
        description=(
            "Inspect or read evidence without mutation. Actions: status, read. Read "
            "memory://operations first for exact payloads and byte limits."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def read_evidence(
        action: Annotated[
            Literal["status", "read"],
            Field(description="Read-only evidence action from memory://operations."),
        ],
        payload: ManagerPayload,
        memory: MemorySelection = None,
    ) -> ManagerResponse:
        if action == "status":
            return _invoke_managed(
                "evidence_status",
                payload,
                memory,
                lambda request: evidence_status(request.digest, memory),
            )
        if action == "read":
            return _invoke_managed(
                "evidence_read",
                payload,
                memory,
                lambda request: evidence_read(
                    request.digest, request.offset, request.limit, memory
                ),
            )
        raise RuntimeError(f"unhandled evidence read action {action!r}")

    @server.tool(
        name="memory_evidence_manage",
        description=(
            "Verify evidence and append verification history. Actions: verify, audit. "
            "These actions never delete evidence."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        structured_output=True,
    )
    def manage_evidence(
        action: Annotated[
            Literal["verify", "audit"],
            Field(description="Mutating evidence action from memory://operations."),
        ],
        payload: ManagerPayload,
        memory: MemorySelection = None,
    ) -> ManagerResponse:
        if action == "verify":
            return _invoke_managed(
                "evidence_verify",
                payload,
                memory,
                lambda request: evidence_verify(request.digest, memory),
            )
        if action == "audit":
            return _invoke_managed(
                "evidence_audit",
                payload,
                memory,
                lambda request: evidence_audit(request.limit, memory),
            )
        raise RuntimeError(f"unhandled evidence action {action!r}")

    return server


def main() -> None:
    application = build_application()
    router = MemoryRouter(application, environment_memory_catalog())
    create_mcp_server(application, router).run()


if __name__ == "__main__":
    main()
