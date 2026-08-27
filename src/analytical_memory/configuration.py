from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.openai import OpenAIEmbeddingProvider
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.application import MemoryApplication
from analytical_memory.ports import MemoryStore
from analytical_memory.schema_contract import load_schema

load_dotenv()


def environment_database() -> Path:
    return Path(os.environ.get("ANALYTICAL_MEMORY_DB", ".local/memory.db"))


def environment_backend() -> str:
    backend = os.environ.get("ANALYTICAL_MEMORY_BACKEND", "sqlite")
    if backend not in {"sqlite", "postgresql"}:
        raise ValueError("ANALYTICAL_MEMORY_BACKEND must be sqlite or postgresql")
    return backend


def environment_postgres_url() -> str | None:
    return os.environ.get("ANALYTICAL_MEMORY_POSTGRES_URL") or None


def environment_postgres_schema() -> str:
    return os.environ.get("ANALYTICAL_MEMORY_POSTGRES_SCHEMA", "public")


def environment_evidence_root() -> Path:
    return Path(os.environ.get("ANALYTICAL_MEMORY_EVIDENCE_ROOT", ".local/evidence"))


def environment_schema() -> Path | None:
    value = os.environ.get("ANALYTICAL_MEMORY_SCHEMA")
    return None if value is None else Path(value)


def user_data_root() -> Path:
    configured = os.environ.get("ANALYTICAL_MEMORY_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "analytical-memory"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "analytical-memory"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "analytical-memory"


load_dotenv(user_data_root() / ".env")


def environment_memory_catalog() -> Path:
    configured = os.environ.get("ANALYTICAL_MEMORY_CATALOG")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else user_data_root() / "memories.json"
    )


def environment_embedding_privacy() -> str:
    return "public"


def build_application(
    *,
    database: Path | None = None,
    evidence_root: Path | None = None,
    schema_path: Path | None = None,
    backend: str | None = None,
    postgres_url: str | None = None,
    postgres_schema: str | None = None,
) -> MemoryApplication:
    selected_backend = backend or environment_backend()
    memory_store: MemoryStore
    if selected_backend == "postgresql":
        from analytical_memory.adapters.postgresql import PostgresMemoryStore

        dsn = postgres_url or environment_postgres_url()
        if dsn is None:
            raise ValueError("ANALYTICAL_MEMORY_POSTGRES_URL is required")
        memory_store = PostgresMemoryStore(
            dsn, schema=postgres_schema or environment_postgres_schema()
        )
    elif selected_backend == "sqlite":
        memory_store = SqliteMemoryStore(database or environment_database())
    else:
        raise ValueError("backend must be sqlite or postgresql")
    return MemoryApplication(
        memory_store=memory_store,
        evidence_store=FileEvidenceStore(evidence_root or environment_evidence_root()),
        schema=load_schema(schema_path or environment_schema()),
        embedding_provider=OpenAIEmbeddingProvider(
            os.environ.get("OPENAI_API_KEY"),
            privacy_ceiling=environment_embedding_privacy(),
        ),
    )
