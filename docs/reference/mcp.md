# MCP Reference

Analytical Memory exposes a local stdio MCP server through the `memory-mcp`
entry point:

```console
uv run memory init
uv run memory-mcp
```

Initialize the selected database and evidence root before connecting a host.
Discovery remains available when they are uninitialized and reports readiness,
but data tools cannot query or apply until the store exists.

The server uses the same application services, schema validation, storage
adapters, and result models as the CLI. Its process configuration is selected
with these optional environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANALYTICAL_MEMORY_DB` | `.local/memory.db` | SQLite database |
| `ANALYTICAL_MEMORY_EVIDENCE_ROOT` | `.local/evidence` | Local evidence store |
| `ANALYTICAL_MEMORY_SCHEMA` | repository `schema/current.json` | Schema document |
| `OPENAI_API_KEY` | unset | Commercial embedding API credential |
| `ANALYTICAL_MEMORY_EMBEDDING_PRIVACY` | `restricted` | Provider privacy ceiling |

Runtime paths are never included in schema or capabilities resources.

## Discovery resources

| URI | Contents |
| --- | --- |
| `memory://schema/current` | Current logical schema and fingerprint |
| `memory://capabilities/current` | Backend, limits, operations, and readiness |
| `memory://schema/queries` | Saved query names and result contracts |
| `memory://schema/ontology/{namespace}` | Namespace discovery template |

The namespace template returns `not_declared` until ontology compilation is
implemented. This makes the discovery URI stable without inventing type
definitions.

## Tools

| Tool | Mutating | Result |
| --- | --- | --- |
| `memory_ingest_preview` | No | Typed preview and stable planned IDs |
| `memory_ingest_apply` | Yes | Typed apply or exact replay result |
| `memory_query_current_facts` | No | Bounded current-facts result |
| `memory_query_current_slots` | No | Single- and multi-valued slot states |
| `memory_query_current_metric` | No | Deterministic current metric selection |
| `memory_traverse_relations` | No | Bounded relation-only traversal |
| `memory_search_text` | No | FTS results with fact provenance |
| `memory_embedding_status` | No | Local profile coverage and readiness |
| `memory_search_semantic` | No | Exact ranking after a remote query embedding |
| `memory_explain` | No | Bounded provenance explanation |
| `memory_explain_relation` | No | Relation assertion provenance |
| `memory_explain_metric` | No | Metric run and evidence provenance |
| `memory_evidence_status` | No | Current provider and effective privacy state |
| `memory_evidence_read` | No | Bounded base64 evidence byte range |
| `memory_evidence_verify` | Yes | Appended object and fragment verification |
| `memory_evidence_audit` | Yes | Bounded verification audit and history |

Ingestion tools take a `batch_path` on the server host. Apply performs the same
schema-fingerprint validation as the CLI. Expected failures are returned as MCP
tool errors with the current fingerprint and schema refresh URI when relevant.

The only raw evidence surface is the explicit bounded read tool; ordinary
queries and explanations never return evidence bytes. The MCP surface does not
expose arbitrary SQL, migrations, snapshots, retirement, or network
transports. Snapshot and retention workflows remain CLI operations because
they create files or retire exact planned local copies.

`memory_search_semantic` is the sole tool in this surface that calls an external
service. It sends the query text to the configured embedding API. Profile
creation and billable document rebuilds remain explicit CLI operations.
