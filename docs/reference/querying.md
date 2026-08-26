# Querying Reference

Milestone 2 adds useful local queries while keeping SQLite details behind the
explicit `MemoryStore` interface.

## Schema and migrations

The generated `schema/current.json` is compiled from sorted JSON fragments in
`schema/metadata/`. Verify that the generated document is current with:

```console
uv run memory schema compile --check
```

SQLite migrations are ordered by `migrations/sqlite/manifest.json`. Each entry
pins the SQL checksum and logical target fingerprint. Migration 2 creates the
ledger and backfills the original migration record when upgrading a version 1
database. Each migration is transactional; a failed migration leaves its prior
storage version intact.

## Slot queries

```console
uv run memory query current-slots
```

A single-valued slot is `missing`, `current`, `contested`, or `conflict`.
Contested candidates never become trusted current values. A multi-valued slot
returns every supported or contested candidate with its individual fact state.

## Relations

Relations are directed canonical facts with assertions and evidence. Traversal
follows relation rows only, defaults to `supported` and `contested`, and
requires bounded depth and result limits:

```console
uv run memory traverse <node-id> --relation-type example:links --max-depth 2
uv run memory explain <relation-id> --kind relation
```

Contradicted or unasserted relations are traversed only when explicitly named
with `--state`.

## Metrics

Metrics are immutable results owned by analytical runs. Current selection uses
an exact definition and canonical dimension set, filters incomplete or
invalidated results, then orders by run recorded time, run ID, and metric ID.

```console
uv run memory query current-metric \
  --definition-version example.count.v1 \
  --dimensions '{"scope":"all"}'
uv run memory explain <metric-id> --kind metric
```

## Full-text search

Only string attributes marked `searchable: true` create `SearchDocument`
records. Search returns canonical facts, assertion provenance, evidence status,
and indexed-versus-eligible coverage without returning raw evidence bytes.

```console
uv run memory search connected --limit 10
```
