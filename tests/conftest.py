from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.ports import MemoryStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(params=("sqlite", "postgresql"), ids=("sqlite", "postgresql"))
def memory_store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[MemoryStore]:
    backend = str(request.param)
    if backend == "sqlite":
        yield SqliteMemoryStore(tmp_path / "memory.db")
        return
    if backend == "postgresql":
        dsn = os.environ.get("ANALYTICAL_MEMORY_TEST_POSTGRES_URL")
        if dsn is None:
            if os.environ.get("CI"):
                pytest.fail(
                    "CI requires ANALYTICAL_MEMORY_TEST_POSTGRES_URL for conformance"
                )
            pytest.skip("ANALYTICAL_MEMORY_TEST_POSTGRES_URL is not configured")
        import psycopg
        from psycopg import sql

        from analytical_memory.adapters.postgresql import PostgresMemoryStore

        schema = f"test_{uuid.uuid4().hex}"
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
            )
        try:
            yield PostgresMemoryStore(dsn, schema=schema)
        finally:
            with psycopg.connect(dsn, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )
        return
    raise AssertionError(f"unregistered test backend: {backend}")


@pytest.fixture
def postgres_store() -> Iterator[MemoryStore]:
    dsn = os.environ.get("ANALYTICAL_MEMORY_TEST_POSTGRES_URL")
    if dsn is None:
        if os.environ.get("CI"):
            pytest.fail(
                "CI requires ANALYTICAL_MEMORY_TEST_POSTGRES_URL for conformance"
            )
        pytest.skip("ANALYTICAL_MEMORY_TEST_POSTGRES_URL is not configured")
    import psycopg
    from psycopg import sql

    from analytical_memory.adapters.postgresql import PostgresMemoryStore

    schema = f"test_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield PostgresMemoryStore(dsn, schema=schema)
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
