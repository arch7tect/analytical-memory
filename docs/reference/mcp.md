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
| `memory://schema/query-ir/current` | Read-only JSON Query IR v1 contract |
| `memory://schema/queries` | Convenience query contracts |
| `memory://capabilities/current` | Backend, limits, operations, and readiness |

The structural fingerprint gates writes. The ontology fingerprint changes when
queryable shape changes, but not when only row counts change.

## M5 tools

| Tool | Mutating | Result |
| --- | --- | --- |
| `memory_ontology_declare_entity` | Yes | Optional constraints and new ontology |
| `memory_jsonl_import` | Yes | Atomic patch/upsert and ontology delta |
| `memory_attribute_write_analysis` | Yes | Current attribute with run provenance |
| `memory_metric_write_analysis` | Yes | Immutable metric with run provenance |
| `memory_join_materialize` | Yes | Join declaration, counts, and relation writes |
| `memory_query_execute` | No | Ordered Query IR rows with direct provenance |
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

The only raw-evidence surface is the bounded read tool. Ordinary query,
ontology, search, and explanation responses never contain evidence bytes. The
MCP surface exposes no arbitrary SQL, migration, snapshot, retention, or network
transport operation. Snapshot, retention, export, and billable embedding rebuild
remain explicit CLI workflows.

`memory_search_semantic` is the only MCP query tool that calls an external
service. Both indexed content and query policy are public-only.
