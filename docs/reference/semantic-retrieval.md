# Semantic retrieval

Milestone 4 uses an explicit `EmbeddingProvider` abstract base class and an
OpenAI adapter fixed to `text-embedding-3-small` with 1536 dimensions.

## Configuration

Copy `.env.template` to `.env` and set `OPENAI_API_KEY`. The `.env` file is
ignored by Git. `ANALYTICAL_MEMORY_EMBEDDING_PRIVACY` defaults to `restricted`,
so all content except explicitly `forbidden` text is eligible. Set a lower
ceiling when needed.

## Workflow

```console
uv run memory embedding create-profile description
uv run memory embedding rebuild <profile-id>
uv run memory embedding status <profile-id>
uv run memory search "query" --semantic-profile <profile-id>
```

A profile is scoped to one node-attribute name. Its ID is derived from the full
provider contract, so changing the model, dimensions, preprocessing, scope, or
privacy ceiling creates a new profile and therefore new embedding records.

Rebuild is explicit because it performs billable remote calls. It sends only
eligible text at or below both privacy ceilings. Inputs are normalized to NFC,
line endings are canonicalized, and surrounding whitespace is removed.

Returned vectors must match the profile's model and dimensions. They are
validated, normalized, and stored as finite little-endian float32 BLOBs.
Search applies exact namespace, node-type, and privacy filters before ranking
all remaining vectors with application-level cosine similarity. Ties use the
document ID, making fixture results deterministic.

If the key is missing or the provider response is invalid, semantic operations
report `degraded`; relational, graph, evidence, and full-text operations remain
available.
