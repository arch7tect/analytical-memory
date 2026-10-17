# Contributing

Analytical Memory requires Python 3.12 or newer and uses `uv` for dependency
management and command execution.

## Setup

```console
git clone https://github.com/arch7tect/analytical-memory.git
cd analytical-memory
uv sync --all-groups --extra postgres --locked
```

Keep secrets and local connection values in the ignored `.env` file. Do not
commit raw evidence, credentials, private fixtures, or developer-specific
paths.

## Verification

Start PostgreSQL 17 with Docker before running the complete SQLite and
PostgreSQL suite. The test Compose project is separate from the normal local
installation and binds port 54329. If that port is already used by the included
local PostgreSQL service, reuse it instead of starting a second container.

```console
docker compose -p analytical-memory-tests up --wait --wait-timeout 60 postgres
```

Run the checks below. The explicit test URL enables PostgreSQL fixtures; each
fixture creates and removes its own isolated schema.

```console
ANALYTICAL_MEMORY_TEST_POSTGRES_URL=postgresql://postgres:analytical_memory_test@127.0.0.1:54329/analytical_memory \
uv run --extra postgres pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python scripts/compile_schema.py --check
uv run python scripts/compile_query_ir_contract.py --check
uv run python scripts/check_docs.py
uv run python scripts/smoke.py
uv run python scripts/benchmark.py --check
uv run memory-quickstart
uv run python scripts/mcp_smoke.py
uv run python scripts/verify_distribution.py
```

After the run, stop the test service while preserving its data:

```console
docker compose -p analytical-memory-tests stop postgres
```

If you reused the normal local service, manage it through its own Compose
project. See the [Docker PostgreSQL guide](docs/reference/backend-portability.md)
for application configuration, readiness checks, and troubleshooting. Running
pytest without the test URL skips PostgreSQL cases locally and is only a
SQLite check; CI requires both backends.

Schema metadata is authoritative. After an intentional contract change,
compile the structural schema first, update migration manifests and checksums,
then regenerate the Query IR contract. Never edit generated schema documents by
hand.

Keep changes bounded and add tests at the public application or shared backend
contract seam. Backend-specific SQL belongs in adapters and migrations; public
request and result shapes must remain backend-neutral.

## Documentation and release artifacts

Use the [documentation index](docs/README.md) for the current guide map and
maintenance rules. Keep setup steps out of the product README and put agent
instructions in packaged resources or skills. Update documentation with behavior
changes, and check links with `uv run python scripts/check_docs.py`.

CI also runs `uv run --locked python scripts/build_release.py` to verify plugin
and distribution packaging. For publication steps, see the
[release guide](docs/releasing.md).
