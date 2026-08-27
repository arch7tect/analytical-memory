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
| `ANALYTICAL_MEMORY_DATA_ROOT` | per-user platform data directory | Base for the named-memory catalog |
| `ANALYTICAL_MEMORY_CATALOG` | `<data-root>/memories.json` | Explicit catalog override |
| `OPENAI_API_KEY` | unset | Commercial embedding API credential |

Secrets are never included in discovery resources. The local catalog resource
does include configured database and evidence paths so a local agent can explain
which target it will use.

## Named memories

The existing environment-selected store is always named `default`. It is not
written to the catalog and remains selected when a data tool omits `memory`.
An explicit unknown or unavailable name fails and never falls back to default.

`memory_configure` is the single lifecycle tool in v1:

- `create` accepts a new or empty target and initializes it;
- `attach` accepts an existing initialized target and performs read-only
  migration-ledger, physical-integrity, and evidence-store readiness checks;
- SQLite uses absolute `database` and `evidence_root` paths;
- PostgreSQL uses `connection_env`, `schema`, and an absolute `evidence_root`.

PostgreSQL connection environment names must match
`ANALYTICAL_MEMORY_*_POSTGRES_URL`. The URL itself belongs in the per-user
`.env`; `memories.json` stores only the environment-variable name. Catalog
writes are locked and atomically replaced. SQLite database paths must be unique,
and evidence roots may neither match nor contain one another. PostgreSQL targets
using the same environment-variable name and schema are rejected. Different
variables containing the same available URL and schema are also rejected. If a
URL is unavailable while the catalog is read, unresolved aliasing remains an
operator responsibility.

The CLI mirrors the same model:

```console
uv run memory memories configure create research \
  --backend sqlite \
  --database /absolute/path/research.db \
  --evidence-root /absolute/path/research-evidence
uv run memory memories list
uv run memory --memory research ontology describe
```

## Discovery resources

| URI | Contents |
| --- | --- |
| `memory://guide` | Source-code-independent selection, discovery, operation, result, safety, and error workflow |
| `memory://schema/current` | Structural contract and fingerprint |
| `memory://schema/ontology/current` | Current derived ontology and fingerprint |
| `memory://schema/ontology/{namespace}` | Namespace-filtered ontology |
| `memory://schema/query-ir/current` | Complete Query IR input/result JSON Schemas, semantics, defaults, limits, and examples |
| `memory://operations` | Concrete manager/action index and operation effects |
| `memory://operations/{operation}` | Exact lazy payload/result schemas, preconditions, errors, and example |
| `memory://schema/queries` | Convenience query contracts |
| `memory://capabilities/current` | Backend, limits, operations, and readiness |
| `memory://catalog` | Default and configured named-memory targets, without secrets |
| `memory://memories/{memory}/capabilities/current` | Capabilities for one memory |
| `memory://memories/{memory}/schema/ontology/current` | Current ontology for one memory |
| `memory://memories/{memory}/schema/ontology/{namespace}` | Namespace-filtered ontology for one memory |

The structural fingerprint gates writes. The ontology fingerprint changes when
queryable shape or its descriptions change, but not when only row counts change.

## MCP tools

| Tool | Actions | Behavior |
| --- | --- | --- |
| `memory_configure` | `create`, `attach` | Typed named-memory lifecycle |
| `memory_ontology_manage` | `declare_entity`, `declare_namespace` | Optional descriptions and validation metadata |
| `memory_ingest_manage` | `jsonl_import`, `analytical_attribute`, `analytical_metric` | Atomic source and analysis ingestion |
| `memory_relation_manage` | `materialize`, `deactivate` | Relation creation and explicit correction |
| `memory_query_manage` | `execute`, `current_metric`, `traverse` | Bounded local relational and graph reads |
| `memory_search_manage` | `text` | Local full-text search |
| `memory_semantic_manage` | `search`, `embedding_status` | Semantic search and provider readiness |
| `memory_explain_manage` | `attribute`, `relation`, `metric` | Direct provenance explanations |
| `memory_evidence_read_manage` | `status`, `read` | Read-only evidence inspection |
| `memory_evidence_manage` | `verify`, `audit` | Verification-history writes; never deletion |
| `memory_node_delete` | — | Isolated destructive current-graph deletion |

JSONL import accepts a server-local `source_path`, a namespaced entity type, an
ordered typed key selector, and the current structural fingerprint. The key is
used only to resolve current nodes during that import. Join materialization is
one explicit call; the server never infers or automatically reruns joins.
Entity, field, and join descriptions are optional schema metadata; an explicit
namespace declaration requires a non-empty description.
They should describe meaning, not contain PII, credentials, or example records.
Redeclaration replaces them; omitted optional descriptions are cleared.

Every data tool accepts optional `memory`. A manager receives `action`, a
`payload` conforming to that operation's lazy specification, and `memory`.
It returns `{action, memory, result}`. Payload validation errors link back to
the exact specification. Successful results and expected errors echo the
resolved or requested memory name.

The only raw-evidence surface is the bounded read tool. Ordinary query,
ontology, search, and explanation responses never contain evidence bytes. The
MCP surface exposes no arbitrary SQL, migration, snapshot, retention, or network
transport operation. Snapshot, retention, export, and billable embedding rebuild
remain explicit CLI workflows.

`memory_semantic_manage` is the only data-query tool with an external-call
boundary. Its `search` action sends public query text to the configured
embedding service; indexed content and query policy remain public-only.
`memory_configure` may also contact a PostgreSQL target while creating or
attaching a named memory.

## Agent contract and errors

Tool inputs and outputs are strict typed objects; unknown members are rejected.
An agent should begin at `memory://guide`, choose a name from
`memory://catalog`, resolve an operation through `memory://operations`, and read
its exact specification before calling the routed manager. Manager schemas stay
compact; operation resources carry complete payload/result descriptions and
examples. Exact general-query syntax remains authoritative at
`memory://schema/query-ir/current`; the shorter `memory://schema/queries`
resource only describes saved convenience queries.

Expected failures use a JSON envelope with `code`, `message`, `details`, and
`retryable`. The stdio MCP transport prepends an error description to this JSON,
so consumers should parse from the first `{`. Error codes and retryability are
discoverable under `errors` in `memory://capabilities/current`. Parameterized
resources return the same envelope as their JSON document for an unknown or
unavailable memory.
