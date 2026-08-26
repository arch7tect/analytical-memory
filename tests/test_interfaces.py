from __future__ import annotations

import inspect

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.openai import OpenAIEmbeddingProvider
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.ports import EmbeddingProvider, EvidenceStore, MemoryStore


def test_adapters_explicitly_inherit_abstract_interfaces() -> None:
    assert inspect.isabstract(EvidenceStore)
    assert inspect.isabstract(MemoryStore)
    assert inspect.isabstract(EmbeddingProvider)
    assert issubclass(FileEvidenceStore, EvidenceStore)
    assert issubclass(SqliteMemoryStore, MemoryStore)
    assert issubclass(OpenAIEmbeddingProvider, EmbeddingProvider)
