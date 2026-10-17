# Backend Portability and Transfer

SQLite is the default embedded backend. PostgreSQL 17 is an optional conforming
backend selected without changing application, CLI, MCP request, or result
shapes.

For initial setup, see [getting started](../getting-started.md) or
[MCP installation](../mcp-installation.md). The base plugin runtime does not
install the PostgreSQL extra; use the standalone source route for PostgreSQL.

## Select a backend

SQLite needs no additional dependency:

```console
uv run memory init
```

For local PostgreSQL, use the included [Docker Compose service](../../compose.yaml).
Install Docker with Compose support and start the Docker engine, then run these
commands from the repository root:

```console
uv sync --locked --extra postgres
docker compose up --wait --wait-timeout 60 postgres
docker compose exec -T postgres pg_isready -U postgres -d analytical_memory
```

Compose runs `postgres:17-alpine`, waits for its health check, and publishes the
database only on `127.0.0.1:54329`. The bundled development database is
`analytical_memory`, its user is `postgres`, and its password is
`analytical_memory_test`. These are local development credentials, also used
by the test suite.

Add the following to the ignored `.env` for this Docker database:

```dotenv
ANALYTICAL_MEMORY_BACKEND=postgresql
ANALYTICAL_MEMORY_POSTGRES_URL=postgresql://postgres:analytical_memory_test@127.0.0.1:54329/analytical_memory
ANALYTICAL_MEMORY_POSTGRES_SCHEMA=analytical_memory
```

Initialize and verify the selected backend:

```console
docker compose exec -T postgres psql -U postgres -d analytical_memory \
  -v ON_ERROR_STOP=1 -c 'CREATE SCHEMA IF NOT EXISTS analytical_memory;'
uv run --extra postgres memory init
uv run --extra postgres memory status
```

`memory init` creates and migrates tables inside an existing schema; it does
not create the schema container. The database role must have permission to
create tables there. The bundled Docker role can create the dedicated schema
with the command above; for another deployment, have its owner create it first.

Keep this environment and the same evidence root when launching the MCP server.
The database runs in Docker; the CLI, MCP process, and evidence directory remain
on the host. For an independently managed PostgreSQL 17 deployment, substitute
its connection URL and schema in `.env`.

To pause the local database while preserving its container and data:

```console
docker compose stop postgres
```

Run the same `up --wait` command to resume it. Database files live in the
PostgreSQL image's data volume; the host evidence directory is separate. Use
the [snapshot procedures](operations.md#snapshot-backup-and-restore) to back up
both canonical records and evidence.

`ANALYTICAL_MEMORY_POSTGRES_SCHEMA` defaults to `public`. A dedicated schema is
recommended when a database is shared. Connection URLs belong in the ignored
`.env` file, never in committed configuration.

Capabilities report `sqlite` or `postgresql` under `storage.backend`. Query IR,
ontology, provenance, error, and MCP contracts are otherwise identical.

Each backend has its own ordered SQL migration sequence. Initialization validates
the shared manifest contract and migration checksums, requires the recorded
ledger to be an exact prefix of the packaged sequence, and applies every pending
migration in one transaction.

## Local PostgreSQL conformance

Use Docker for the complete SQLite and PostgreSQL test run. A separate Compose
project keeps test containers apart from the normal local installation. Port
54329 must be available; if the normal local Compose service is already running,
reuse that service and skip the test-container startup command.

```console
uv sync --all-groups --extra postgres --locked
docker compose -p analytical-memory-tests up --wait --wait-timeout 60 postgres
docker compose -p analytical-memory-tests exec -T postgres pg_isready -U postgres -d analytical_memory
ANALYTICAL_MEMORY_TEST_POSTGRES_URL=postgresql://postgres:analytical_memory_test@127.0.0.1:54329/analytical_memory \
uv run --extra postgres pytest -q
docker compose -p analytical-memory-tests stop postgres
```

The test URL is independent of `ANALYTICAL_MEMORY_POSTGRES_URL`; it enables
PostgreSQL fixtures without switching the application's default backend. Tests
create unique `test_<uuid>` schemas and remove only those schemas on completion.
When reusing an existing local service, leave its lifecycle under the normal
Compose project instead of running the test project's `stop` command.

Without `ANALYTICAL_MEMORY_TEST_POSTGRES_URL`, local PostgreSQL cases are
reported as skipped. CI always supplies PostgreSQL 17 and fails on a conformance
failure. A full local verification must enable these cases rather than accept
their absence as a successful PostgreSQL check.

If startup fails, check `docker compose -p analytical-memory-tests ps --all`
and `docker compose -p analytical-memory-tests logs postgres`. A port conflict
means another process owns 54329; a Docker connection error means the engine
is unavailable. Use the corresponding commands without `-p` for the normal
local service.

## Transfer SQLite to PostgreSQL

Export reads the source only and writes a new canonical artifact:

```console
uv run memory transfer export memory-transfer.json
```

The artifact preserves canonical IDs, timestamps, provenance, current values,
relations, and metrics. It excludes backend sort and full-text projections.
The document contains per-table counts and hashes, the structural and ontology
fingerprints, and a content-derived transfer ID.

Initialize and import into an empty PostgreSQL schema. Use a separate target
configuration so exporting still reads the original SQLite source. With the
target connection held in the environment and the target schema already created
as described above:

```console
ANALYTICAL_MEMORY_BACKEND=postgresql \
ANALYTICAL_MEMORY_POSTGRES_SCHEMA=analytical_memory \
uv run memory init

ANALYTICAL_MEMORY_BACKEND=postgresql \
ANALYTICAL_MEMORY_POSTGRES_SCHEMA=analytical_memory \
uv run memory transfer import memory-transfer.json
```

Import verifies the artifact before writing, then writes canonical records and
rebuilds PostgreSQL sort and full-text projections in one transaction. A write
or constraint failure rolls back that transaction. After commit it compares
every canonical table hash and the ontology fingerprint. A post-commit
verification failure leaves the target populated but unselected. Preserve it
for investigation; recreate only its dedicated target after explicitly
deciding to discard that failed import. No failure changes the source
database or evidence bytes. Configuration is never switched automatically;
select PostgreSQL only after the command returns `verified: true` and
representative queries have been checked.

Keep the SQLite database and evidence directory unchanged as rollback artifacts
until operational acceptance is complete.

Transfer artifacts exclude raw evidence bytes, embedding profiles, and vectors.
Keep the original evidence root available to the selected backend, or separately
copy and verify it before cutover. See [operations](operations.md) and
[evidence portability](evidence-portability.md) for private snapshots when the
backup must include raw evidence.
