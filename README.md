# Analytical Memory

Analytical Memory is an evidence-backed, local-first memory for durable facts,
provenance, and reproducible analysis. The first working slice uses SQLite for
canonical records and a content-addressed local filesystem for raw evidence.

The application core depends on explicit abstract interfaces. Storage adapters
implement those interfaces through inheritance, keeping the path open for a
PostgreSQL backend without coupling use cases to SQLite.

## Quickstart

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required.

```console
uv sync --all-groups --locked
uv run memory init
uv run memory ingest preview examples/quickstart/batch.json
uv run memory ingest apply examples/quickstart/batch.json
uv run memory query current-facts
uv run memory explain 51a612e1-68be-566e-8549-b3ba9f0becfb
```

The commands write local state under the ignored `.local/` directory. Preview
does not write, repeated apply is idempotent, current-facts returns all four
fact states, and explain verifies the referenced evidence object by SHA-256.

Run the complete synthetic smoke path without retaining state:

```console
uv run python scripts/smoke.py
```

## Development

```console
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

See the [system design](docs/design.md) and
[implementation plan](docs/implementation-plan.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
