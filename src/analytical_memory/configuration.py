from __future__ import annotations

import os
from pathlib import Path

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.application import MemoryApplication
from analytical_memory.schema_contract import load_schema


def environment_database() -> Path:
    return Path(os.environ.get("ANALYTICAL_MEMORY_DB", ".local/memory.db"))


def environment_evidence_root() -> Path:
    return Path(os.environ.get("ANALYTICAL_MEMORY_EVIDENCE_ROOT", ".local/evidence"))


def environment_schema() -> Path | None:
    value = os.environ.get("ANALYTICAL_MEMORY_SCHEMA")
    return None if value is None else Path(value)


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
    )
