from __future__ import annotations

from pathlib import Path

import pytest

from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.ports import MemoryStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(params=("sqlite",), ids=("sqlite",))
def memory_store(request: pytest.FixtureRequest, tmp_path: Path) -> MemoryStore:
    backend = str(request.param)
    if backend == "sqlite":
        return SqliteMemoryStore(tmp_path / "memory.db")
    raise AssertionError(f"unregistered test backend: {backend}")
