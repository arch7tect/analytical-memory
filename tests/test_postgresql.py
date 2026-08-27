from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.application import MemoryApplication
from analytical_memory.canonical import canonical_json, sha256_bytes
from analytical_memory.domain import (
    EmbeddingBatch,
    EmbeddingProviderInfo,
)
from analytical_memory.errors import BatchValidationError
from analytical_memory.migrations import default_migrations_directory
from analytical_memory.ports import EmbeddingProvider, MemoryStore
from analytical_memory.resources import resource_path
from analytical_memory.schema_contract import load_schema


class FixtureEmbeddingProvider(EmbeddingProvider):
    @property
    def info(self) -> EmbeddingProviderInfo:
        return EmbeddingProviderInfo(
            provider="fixture",
            model="fixture-v1",
            dimensions=3,
            preprocessing_version="unicode-nfc-lines-v1",
            privacy_ceiling="public",
            configured=True,
        )

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        vectors = tuple(
            (1.0, 0.0, 0.0)
            if "running" in text
            else (0.0, 1.0, 0.0)
            if "run" in text
            else (0.0, 0.0, 1.0)
            for text in texts
        )
        return EmbeddingBatch(vectors=vectors, response_model="fixture-v1")


def _write(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _application(
    store: MemoryStore,
    evidence_root: Path,
    provider: EmbeddingProvider | None = None,
) -> MemoryApplication:
    application = MemoryApplication(
        store, FileEvidenceStore(evidence_root), load_schema(), provider
    )
    application.initialize()
    return application


def _query(application: MemoryApplication) -> dict[str, Any]:
    return application.execute_query(
        {
            "query_ir_version": "1",
            "match": {"nodes": [{"type": "example.Session", "as": "session"}]},
            "return": [
                {"field": "session.id"},
                {"field": "session.status"},
            ],
            "order_by": [{"field": "session.status", "direction": "asc"}],
        }
    )


def _populate(application: MemoryApplication, tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fingerprint = application.schema.fingerprint
    application.declare_entity(
        "example.Session",
        fields={
            "status": {"type": "string", "searchable": True},
            "note": {"type": "string", "searchable": True},
        },
        contract_fingerprint=fingerprint,
    )
    for path, entity_type in (
        (
            _write(
                tmp_path / "sessions.jsonl",
                [
                    {"id": "s1", "status": "Item10", "note": "the running"},
                    {"id": "s2", "status": "item2", "note": "run"},
                    {"id": "s3", "status": "ITEM1", "note": "other"},
                ],
            ),
            "example.Session",
        ),
        (
            _write(
                tmp_path / "messages.jsonl",
                [{"id": "m1", "session_id": "s2", "text": "running the test"}],
            ),
            "example.Message",
        ),
    ):
        application.jsonl_import(
            path,
            entity_type=entity_type,
            key=[{"field": "id", "type": "string"}],
            contract_fingerprint=fingerprint,
        )
    application.materialize_join(
        name="message_to_session",
        relation="session",
        from_={"type": "example.Message", "fields": ["session_id"]},
        to={"type": "example.Session", "fields": ["id"]},
        contract_fingerprint=fingerprint,
    )


def test_sqlite_to_postgresql_transfer_preserves_canonical_behavior(
    postgres_store: MemoryStore, tmp_path: Path
) -> None:
    evidence_root = tmp_path / "evidence"
    source = _application(SqliteMemoryStore(tmp_path / "source.db"), evidence_root)
    _populate(source, tmp_path)
    before = canonical_json(source.memory_store.transfer_records())
    source_query = _query(source)
    artifact = tmp_path / "transfer.json"
    exported = source.transfer_export(artifact, created_at="2026-01-01T00:00:00Z")

    target = _application(postgres_store, evidence_root)
    imported = target.transfer_import(artifact)

    assert imported["verified"] is True
    assert imported["transfer_id"] == exported["transfer_id"]
    assert canonical_json(target.memory_store.transfer_records()) == before
    assert _query(target) == source_query
    for text in ("the", "run", "running", "the running"):
        source_search = source.search_text(text)
        target_search = target.search_text(text)
        assert {item["document_id"] for item in target_search["results"]} == {
            item["document_id"] for item in source_search["results"]
        }
        assert target_search["coverage"] == source_search["coverage"]
        assert [item["rank"] for item in target_search["results"]] == sorted(
            item["rank"] for item in target_search["results"]
        )
    range_document = {
        "query_ir_version": "1",
        "match": {"nodes": [{"type": "example.Session", "as": "session"}]},
        "where": [
            {
                "left": {"field": "session.status"},
                "op": "gte",
                "right": {"value": "Item10"},
            }
        ],
        "return": [{"field": "session.id"}],
        "order_by": [{"field": "session.status", "direction": "asc"}],
    }
    assert target.execute_query(range_document) == source.execute_query(range_document)
    assert canonical_json(source.memory_store.transfer_records()) == before


def test_postgresql_exact_vector_engine_matches_sqlite(
    postgres_store: MemoryStore, tmp_path: Path
) -> None:
    provider = FixtureEmbeddingProvider()
    evidence_root = tmp_path / "evidence"
    sqlite = _application(
        SqliteMemoryStore(tmp_path / "sqlite.db"),
        evidence_root,
        provider,
    )
    _populate(sqlite, tmp_path / "sqlite")
    artifact = tmp_path / "transfer.json"
    sqlite.transfer_export(artifact, created_at="2026-01-01T00:00:00Z")
    postgres = _application(postgres_store, evidence_root, provider)
    postgres.transfer_import(artifact)

    sqlite_profile = sqlite.embedding_profile_create("note")["profile"]
    postgres_profile = postgres.embedding_profile_create("note")["profile"]
    sqlite.embedding_rebuild(sqlite_profile["id"])
    postgres.embedding_rebuild(postgres_profile["id"])
    sqlite_result = sqlite.search_semantic(sqlite_profile["id"], "running", limit=3)
    postgres_result = postgres.search_semantic(
        postgres_profile["id"], "running", limit=3
    )

    assert [item["value"] for item in postgres_result["results"]] == [
        item["value"] for item in sqlite_result["results"]
    ]
    assert [item["score"] for item in postgres_result["results"]] == [
        item["score"] for item in sqlite_result["results"]
    ]
    assert postgres_result["coverage"] == sqlite_result["coverage"]


def test_backend_manifests_target_the_same_logical_schema() -> None:
    sqlite = json.loads(
        (default_migrations_directory() / "manifest.json").read_text(encoding="utf-8")
    )
    postgresql = json.loads(
        resource_path("migrations", "postgresql", "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        sqlite["migrations"][-1]["target_fingerprint"]
        == postgresql["migrations"][-1]["target_fingerprint"]
        == load_schema().fingerprint
    )
    migration = postgresql["migrations"][-1]
    assert (
        sha256_bytes(
            resource_path("migrations", "postgresql", migration["file"]).read_bytes()
        )
        == migration["checksum"]
    )


def test_failed_postgresql_transfer_rolls_back_without_changing_source(
    postgres_store: MemoryStore, tmp_path: Path
) -> None:
    evidence_root = tmp_path / "evidence"
    source = _application(SqliteMemoryStore(tmp_path / "source.db"), evidence_root)
    _populate(source, tmp_path)
    source_before = canonical_json(source.memory_store.transfer_records())
    valid = tmp_path / "valid.json"
    source.transfer_export(valid, created_at="2026-01-01T00:00:00Z")
    document = json.loads(valid.read_text(encoding="utf-8"))
    document["records"]["relation"][0]["target_node_id"] = "missing-node"
    document["table_hashes"]["relation"] = sha256_bytes(
        canonical_json(document["records"]["relation"]).encode("utf-8")
    )
    identity = dict(document)
    identity.pop("transfer_id")
    document["transfer_id"] = sha256_bytes(canonical_json(identity).encode("utf-8"))
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(document), encoding="utf-8")

    target = _application(postgres_store, evidence_root)
    with pytest.raises(BatchValidationError):
        target.transfer_import(invalid)

    assert all(not rows for rows in target.memory_store.transfer_records().values())
    assert canonical_json(source.memory_store.transfer_records()) == source_before
