# Text and semantic retrieval

Local full-text search needs no external service. Semantic search optionally
uses the OpenAI embedding adapter, fixed to `text-embedding-3-small` with 1536
dimensions. Both search current text attributes; neither searches arbitrary raw
evidence bytes. Start with [getting started](../getting-started.md) to load the
sample memory used below.

## Enable local text search

Imported fields are not searchable by default. Mark the desired string field
`searchable` in its entity declaration. Replace `<contract-fingerprint>` with
`schema_fingerprint` from `uv run memory schema show`:

```console
uv run memory ontology declare-entity example.SessionMessage \
  --fields '{"message":{"types":["string"],"searchable":true}}' \
  --contract-fingerprint <contract-fingerprint>
uv run memory search "First"
```

Redeclaration updates search eligibility for existing values. A declaration
replaces the previous declaration, so include all constraints, descriptions,
and privacy settings you want to retain when updating an existing entity.
Full-text search may return private fields when they are searchable. Privacy
controls public export and external embeddings, not access by the local process.

## Configure optional semantic search

Set `OPENAI_API_KEY` in the ignored checkout `.env`, or in the per-user plugin
configuration described in [plugin installation](../plugin-installation.md#local-data).
Core import, structured queries, traversal, and local full-text search need no
API key. External embeddings exclude private entities and fields before any
provider call.

```console
uv run memory embedding create-profile message
uv run memory embedding rebuild <profile-id>
uv run memory embedding status <profile-id>
uv run memory search "first message" --semantic-profile <profile-id>
```

Replace `<profile-id>` with the returned profile ID. A profile is scoped to one
attribute name. Its ID is derived from the full provider contract, so changing
the model, dimensions, preprocessing, or scope creates a new profile and new
embedding records.

Rebuild is explicit because it performs billable remote calls. It sends only
public eligible text. Semantic search sends the query text to the same provider
when indexed candidates are available; use public query text only. MCP exposes
semantic search and status, while profile creation and rebuild remain CLI
operations.

## Ranking and readiness

Inputs are normalized to NFC, line endings are canonicalized, and surrounding
whitespace is removed. Returned vectors must match the profile's model and
dimensions. They are validated, normalized, and stored as finite little-endian
float32 BLOBs.

Semantic search applies optional namespace and node-type filters before ranking
current public candidates by application-level cosine similarity. Ties use the
document ID. Arbitrary field predicates and graph-pattern filters are separate
structured queries; they are not semantic-search arguments.

Results include eligible/indexed coverage. A missing key or invalid provider
response yields `degraded` when an embedding call is needed; an empty candidate
set can return a ready empty result when coverage is complete. Other local
operations remain available. After a snapshot restore or backend transfer,
recreate profiles and rebuild embeddings explicitly. See
[evidence portability](evidence-portability.md) and [MCP](mcp.md) for the related
contracts.
