# Backend Portability and Transfer

SQLite is the default embedded backend. PostgreSQL 17 is an optional conforming
backend selected without changing application, CLI, MCP request, or result
shapes.

## Select a backend

SQLite needs no additional dependency:

```console
uv run memory init
```

Install PostgreSQL support and select it through configuration:

```console
uv sync --extra postgres
ANALYTICAL_MEMORY_BACKEND=postgresql \
ANALYTICAL_MEMORY_POSTGRES_URL=postgresql://user:password@host/database \
uv run memory init
```

`ANALYTICAL_MEMORY_POSTGRES_SCHEMA` defaults to `public`. A dedicated schema is
recommended when a database is shared. Connection URLs belong in the ignored
`.env` file, never in committed configuration.

Capabilities report `sqlite` or `postgresql` under `storage.backend`. Query IR,
ontology, provenance, error, and MCP contracts are otherwise identical.

## Local PostgreSQL conformance

The included Compose service exposes PostgreSQL 17 on local port 54329:

```console
docker compose up -d postgres
ANALYTICAL_MEMORY_TEST_POSTGRES_URL=postgresql://postgres:analytical_memory_test@127.0.0.1:54329/analytical_memory \
uv run pytest
docker compose down
```

Without `ANALYTICAL_MEMORY_TEST_POSTGRES_URL`, local PostgreSQL cases are
reported as skipped. CI always supplies PostgreSQL 17 and fails on a conformance
failure.

## Transfer SQLite to PostgreSQL

Export reads the source only and writes a new canonical artifact:

```console
uv run memory transfer export memory-transfer.json
```

The artifact preserves canonical IDs, timestamps, provenance, current values,
relations, and metrics. It excludes backend sort and full-text projections.
The document contains per-table counts and hashes, the structural and ontology
fingerprints, and a content-derived transfer ID.

Initialize and import into an empty PostgreSQL schema:

```console
ANALYTICAL_MEMORY_BACKEND=postgresql \
ANALYTICAL_MEMORY_POSTGRES_URL=postgresql://user:password@host/database \
ANALYTICAL_MEMORY_POSTGRES_SCHEMA=analytical_memory \
uv run memory transfer import memory-transfer.json
```

Import verifies the artifact before writing, then writes canonical records and
rebuilds PostgreSQL sort and full-text projections in one transaction. A write
or constraint failure rolls back that transaction. After commit it compares
every canonical table hash and the ontology fingerprint. A post-commit
verification failure leaves the target populated but unselected; drop and
recreate its dedicated schema before retrying. No failure changes the source
database or evidence bytes. Configuration is never switched automatically;
select PostgreSQL only after the command returns `verified: true` and
representative queries have been checked.

Keep the SQLite database and evidence directory unchanged as rollback artifacts
until operational acceptance is complete.
