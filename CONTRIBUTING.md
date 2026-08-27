# Contributing

Analytical Memory requires Python 3.12 or newer and uses `uv` for dependency
management and command execution.

## Setup

```console
uv sync --all-groups --extra postgres --locked
```

Keep secrets and local connection values in the ignored `.env` file. Do not
commit raw evidence, credentials, private fixtures, or developer-specific
paths.

## Verification

Run the complete local SQLite suite:

```console
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run python scripts/compile_schema.py --check
uv run python scripts/compile_query_ir_contract.py --check
uv run python scripts/benchmark.py --check
uv run python scripts/verify_distribution.py
```

For PostgreSQL conformance, start the included PostgreSQL 17 service and set the
test URL as described in
[`docs/reference/backend-portability.md`](docs/reference/backend-portability.md).

Schema metadata is authoritative. After an intentional contract change,
compile the structural schema first, update migration manifests and checksums,
then regenerate the Query IR contract. Never edit generated schema documents by
hand.

Keep changes bounded and add tests at the public application or shared backend
contract seam. Backend-specific SQL belongs in adapters and migrations; public
request and result shapes must remain backend-neutral.
