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
| `memory_explain` | No | Bounded provenance explanation |

Ingestion tools take a `batch_path` on the server host. Apply performs the same
schema-fingerprint validation as the CLI. Expected failures are returned as MCP
tool errors with the current fingerprint and schema refresh URI when relevant.

The MCP surface does not expose raw evidence reads, arbitrary SQL, migrations,
network transports, or retention operations. Explanations return evidence
metadata and current verification status, never evidence bytes.
