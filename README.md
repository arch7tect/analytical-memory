# Analytical Memory

Analytical Memory is an evidence-backed, local-first memory whose ontology grows
with the data it receives. Clients can discover the current ontology, import new
object types incrementally, create explicit graph relations, run relational and
graph queries through a backend-neutral JSON Query IR, and trace current values
to their source and raw evidence.

SQLite stores canonical records and a content-addressed local filesystem stores
raw evidence. The application depends on explicit abstract interfaces so a
PostgreSQL adapter can replace SQLite without changing the public use cases.

## Current status

Milestones 0 through 5 are implemented. M5 is a clean-break contract with:

- streaming, atomic JSONL patch/upsert;
- optional entity declarations and a data-derived current ontology;
- explicit one-step joins between independently loaded datasets;
- read-only JSON Query IR v1;
- one current `NodeAttribute` or `Relation` with direct provenance;
- analytical values written through the same attribute shape;
- `public` and `private` privacy, with public-only export and external embedding;
- local evidence, verification, snapshots, and public sanitized export.

There are no Finding or Assertion records in M5. Development databases created
with the earlier contract are reinitialized by migration 005.

## Quickstart

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required.

```console
uv sync --all-groups --locked
uv run memory init
uv run memory schema show
```

Use the `schema_fingerprint` returned by `schema show` as
`<contract-fingerprint>` below:

```console
uv run memory jsonl import examples/quickstart/sessions.jsonl \
  --entity-type example.Session \
  --key '[{"field":"id","type":"string"}]' \
  --contract-fingerprint <contract-fingerprint>

uv run memory jsonl import examples/quickstart/messages.jsonl \
  --entity-type example.SessionMessage \
  --key '[{"field":"id","type":"string"}]' \
  --contract-fingerprint <contract-fingerprint>

uv run memory ontology describe

uv run memory join materialize examples/quickstart/join.json \
  --contract-fingerprint <contract-fingerprint>

uv run memory query execute --document examples/quickstart/query.json
```

The commands write local state under the ignored `.local/` directory. Import
keys are lookup expressions, not persistent identity records. Repeating the
same import is idempotent; a later record patches only the fields it contains.

## MCP

Initialize the selected stores and start the local stdio server:

```console
uv run memory init
uv run memory-mcp
```

An MCP client should first read `memory://schema/current`,
`memory://schema/ontology/current`, and `memory://schema/query-ir/current`.
It can then import JSONL files, declare optional constraints, materialize joins,
write analytical attributes, and execute Query IR without direct database
access. See the [MCP reference](docs/reference/mcp.md).

## Semantic retrieval

Copy `.env.template` to the ignored `.env` and set `OPENAI_API_KEY`. Only public
search documents can be sent to the configured external embedding provider.

```console
uv run memory embedding create-profile description
uv run memory embedding rebuild <profile-id>
uv run memory search "related text" --semantic-profile <profile-id>
```

## Development

```console
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python scripts/compile_schema.py --check
```

See the [system design](docs/design.md),
[implementation plan](docs/implementation-plan.md), and
[ADR 0001](docs/decisions/0001-dynamic-ontology-query-ir.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
