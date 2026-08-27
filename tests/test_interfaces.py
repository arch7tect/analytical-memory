from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.openai import OpenAIEmbeddingProvider
from analytical_memory.adapters.sql_store import SqlMemoryStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.ports import EmbeddingProvider, EvidenceStore, MemoryStore


def test_adapters_explicitly_inherit_abstract_interfaces() -> None:
    assert inspect.isabstract(EvidenceStore)
    assert inspect.isabstract(MemoryStore)
    assert inspect.isabstract(EmbeddingProvider)
    assert inspect.isabstract(SqlMemoryStore)
    assert issubclass(FileEvidenceStore, EvidenceStore)
    assert issubclass(SqliteMemoryStore, MemoryStore)
    assert issubclass(OpenAIEmbeddingProvider, EmbeddingProvider)


def test_shared_read_scope_closes_sqlite_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteMemoryStore(tmp_path / "memory.db")
    store.initialize()
    connection = store._connect()
    monkeypatch.setattr(store, "_connect", lambda **_: connection)

    assert store.evidence_digests(1) == ([], False)

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
