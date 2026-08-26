from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.application import MemoryApplication
from analytical_memory.ports import MemoryStore
from analytical_memory.schema_contract import SchemaContract, load_schema

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True)
class ApplicationFixture:
    application: MemoryApplication
    batch_path: Path
    database: Path
    evidence_store: FileEvidenceStore
    memory_store: MemoryStore
    schema: SchemaContract


@pytest.fixture(params=("sqlite",), ids=("sqlite",))
def memory_store(request: pytest.FixtureRequest, tmp_path: Path) -> MemoryStore:
    backend = str(request.param)
    if backend == "sqlite":
        return SqliteMemoryStore(tmp_path / "memory.db")
    raise AssertionError(f"unregistered test backend: {backend}")


@pytest.fixture
def application_fixture(
    tmp_path: Path, memory_store: MemoryStore
) -> ApplicationFixture:
    example = tmp_path / "quickstart"
    shutil.copytree(REPOSITORY_ROOT / "examples" / "quickstart", example)
    schema = load_schema(REPOSITORY_ROOT / "schema" / "current.json")
    database = tmp_path / "memory.db"
    evidence_store = FileEvidenceStore(tmp_path / "evidence")
    application = MemoryApplication(memory_store, evidence_store, schema)
    return ApplicationFixture(
        application=application,
        batch_path=example / "batch.json",
        database=database,
        evidence_store=evidence_store,
        memory_store=memory_store,
        schema=schema,
    )


@pytest.fixture
def querying_batch_path(tmp_path: Path) -> Path:
    example = tmp_path / "querying"
    shutil.copytree(REPOSITORY_ROOT / "examples" / "querying", example)
    return example / "batch.json"
