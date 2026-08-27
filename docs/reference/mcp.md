# MCP Reference

Analytical Memory exposes a local stdio MCP server through `memory-mcp`:

```console
uv run memory init
uv run memory-mcp
```

Initialize the selected database and evidence root before using data tools.
Discovery remains available while a store is uninitialized.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANALYTICAL_MEMORY_DB` | `.local/memory.db` | SQLite database |
| `ANALYTICAL_MEMORY_BACKEND` | `sqlite` | `sqlite` or `postgresql` |
| `ANALYTICAL_MEMORY_POSTGRES_URL` | unset | PostgreSQL connection URL when selected |
| `ANALYTICAL_MEMORY_POSTGRES_SCHEMA` | `public` | PostgreSQL schema |
| `ANALYTICAL_MEMORY_EVIDENCE_ROOT` | `.local/evidence` | Local evidence store |
| `ANALYTICAL_MEMORY_SCHEMA` | packaged `schema/current.json` | Structural contract |
| `OPENAI_API_KEY` | unset | Commercial embedding API credential |

Runtime paths and secrets are never included in discovery resources.

## Discovery resources

| URI | Contents |
| --- | --- |
| `memory://schema/current` | Structural contract and fingerprint |
| `memory://schema/ontology/current` | Current derived ontology and fingerprint |
| `memory://schema/ontology/{namespace}` | Namespace-filtered ontology |
| `memory://schema/query-ir/current` | Complete Query IR input/result JSON Schemas, semantics, defaults, limits, and examples |
| `memory://schema/queries` | Convenience query contracts |
| `memory://capabilities/current` | Backend, limits, operations, and readiness |

The structural fingerprint gates writes. The ontology fingerprint changes when
queryable shape or its descriptions change, but not when only row counts change.

## M5 tools

| Tool | Mutating | Result |
| --- | --- | --- |
| `memory_ontology_declare_namespace` | Yes | Namespace description and new ontology |
| `memory_ontology_declare_entity` | Yes | Optional constraints and new ontology |
| `memory_jsonl_import` | Yes | Atomic patch/upsert and ontology delta |
| `memory_attribute_write_analysis` | Yes | Current attribute with run provenance |
| `memory_metric_write_analysis` | Yes | Immutable metric with run provenance |
| `memory_join_materialize` | Yes | Join declaration, counts, and relation writes |
| `memory_query_execute` | No | Ordered Query IR rows with node bindings and direct provenance |
| `memory_relation_deactivate` | Yes | Explicit current relation correction |
| `memory_node_delete` | Yes | Cascaded current graph deletion counts |
| `memory_traverse_relations` | No | Bounded active-relation traversal |
| `memory_search_text` | No | Local FTS results with direct provenance |
| `memory_embedding_status` | No | Profile coverage and provider readiness |
| `memory_search_semantic` | No | Exact local ranking after remote query embedding |
| `memory_explain` | No | Current attribute and direct evidence provenance |
| `memory_explain_relation` | No | Current relation and direct evidence provenance |
| `memory_query_current_metric` | No | Deterministic current metric selection |
| `memory_explain_metric` | No | Metric run and evidence provenance |
| `memory_evidence_status` | No | Current provider and privacy state |
| `memory_evidence_read` | No | Bounded base64 evidence byte range |
| `memory_evidence_verify` | Yes | Appended verification history |
| `memory_evidence_audit` | Yes | Bounded evidence audit |

JSONL import accepts a server-local `source_path`, a namespaced entity type, an
ordered typed key selector, and the current structural fingerprint. The key is
used only to resolve current nodes during that import. Join materialization is
one explicit call; the server never infers or automatically reruns joins.
Entity, field, and join descriptions are optional schema metadata; an explicit
namespace declaration requires a non-empty description.
They should describe meaning, not contain PII, credentials, or example records.
Redeclaration replaces them; omitted optional descriptions are cleared.

The only raw-evidence surface is the bounded read tool. Ordinary query,
ontology, search, and explanation responses never contain evidence bytes. The
MCP surface exposes no arbitrary SQL, migration, snapshot, retention, or network
transport operation. Snapshot, retention, export, and billable embedding rebuild
remain explicit CLI workflows.

`memory_search_semantic` is the only MCP query tool that calls an external
service. Both indexed content and query policy are public-only.

## Agent contract and errors

Tool inputs and outputs are strict typed objects; unknown members are rejected.
An agent should discover tools from `memory://capabilities/current`, queryable
shape from `memory://schema/ontology/current`, and exact Query IR syntax from
`memory://schema/query-ir/current`. The latter resource is authoritative; the
shorter `memory://schema/queries` resource only describes saved convenience
queries.

Expected failures use a JSON envelope with `code`, `message`, `details`, and
`retryable`. The stdio MCP transport prepends an error description to this JSON,
so consumers should parse from the first `{`. Error codes and retryability are
discoverable under `errors` in `memory://capabilities/current`.
