from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.openai import OpenAIEmbeddingProvider
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.application import MemoryApplication
from analytical_memory.evidence import PRIVACY_ORDER
from analytical_memory.schema_contract import load_schema

load_dotenv()


def environment_database() -> Path:
    return Path(os.environ.get("ANALYTICAL_MEMORY_DB", ".local/memory.db"))


def environment_evidence_root() -> Path:
    return Path(os.environ.get("ANALYTICAL_MEMORY_EVIDENCE_ROOT", ".local/evidence"))


def environment_schema() -> Path | None:
    value = os.environ.get("ANALYTICAL_MEMORY_SCHEMA")
    return None if value is None else Path(value)


def environment_embedding_privacy() -> str:
    value = os.environ.get("ANALYTICAL_MEMORY_EMBEDDING_PRIVACY", "restricted")
    if value not in PRIVACY_ORDER or value == "forbidden":
        raise ValueError(f"unknown ANALYTICAL_MEMORY_EMBEDDING_PRIVACY: {value}")
    return value


def build_application(
    *,
    database: Path | None = None,
    evidence_root: Path | None = None,
    schema_path: Path | None = None,
) -> MemoryApplication:
    return MemoryApplication(
        memory_store=SqliteMemoryStore(database or environment_database()),
        evidence_store=FileEvidenceStore(evidence_root or environment_evidence_root()),
        schema=load_schema(schema_path or environment_schema()),
        embedding_provider=OpenAIEmbeddingProvider(
            os.environ.get("OPENAI_API_KEY"),
            privacy_ceiling=environment_embedding_privacy(),
        ),
    )
