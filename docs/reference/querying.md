# Querying Reference

M5 uses a backend-neutral, read-only JSON Query IR for relational and fixed
graph-pattern queries. SQLite is an implementation detail behind the
`MemoryStore` abstract interface.

## Discover before querying

Read the current ontology through MCP or CLI:

```console
uv run memory ontology describe
uv run memory ontology describe --namespace example
```

The ontology lists entity types, fields, exact effective JSON types, declared
constraints, search eligibility, explicit join declarations, and statistics.
Its fingerprint excludes row counts, so clients replan when queryable shape
changes rather than whenever data volume changes.

## Query IR v1

A query contains:

- `query_ir_version: "1"`;
- fixed node and optional edge patterns;
- an optional conjunctive `where` list;
- projections or `count`;
- optional deterministic ordering, limit, and offset.

Field references use `<alias>.<attribute>`. Supported predicates are `eq`,
`ne`, `lt`, `lte`, `gt`, `gte`, `in`, and `exists`. Comparisons are type-strict;
the engine never coerces strings to numbers or numbers to strings.

```console
uv run memory query execute --document examples/quickstart/query.json
```

Each projected attribute contains its current record ID and direct source,
batch, run, evidence-fragment, and update-time provenance. Query results also
contain deterministic ordering, truncation state, and the ontology fingerprint.

## Relations and traversal

Relations are directed current records with an `active` flag and direct
provenance. Only an explicit join materialization creates them; importing later
records never runs a stored join automatically.

```console
uv run memory join materialize examples/quickstart/join.json \
  --contract-fingerprint <contract-fingerprint>
uv run memory traverse <node-id> --relation-type session --max-depth 2
uv run memory explain <relation-id> --kind relation
```

Deactivation is an explicit correction. A later join rerun does not reactivate
that relation. Deleting either endpoint cascades the relation.

## Full-text and semantic search

Only declared searchable string attributes produce `SearchDocument` records.
Full-text search is local. Semantic search uses exact application-level cosine
ranking, while only public text may be sent to an external embedding provider.
Both return direct current provenance and never raw evidence bytes.

```console
uv run memory search "connected" --limit 10
uv run memory search "related text" --semantic-profile <profile-id>
```

Variable-length paths, grouping, cursor pagination, textual GQL parsing, and
text or vector ranking inside Query IR are deferred.
