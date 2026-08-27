from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.application import MemoryApplication
from analytical_memory.errors import StoreNotInitializedError
from analytical_memory.jsonl import iter_jsonl as original_iter_jsonl
from analytical_memory.ports import MemoryStore
from analytical_memory.schema_contract import load_schema


def _application(store: MemoryStore, evidence: Path) -> MemoryApplication:
    application = MemoryApplication(store, FileEvidenceStore(evidence), load_schema())
    application.initialize()
    return application


def _write(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _import(application: MemoryApplication, source: Path) -> dict[str, Any]:
    return application.jsonl_import(
        source,
        entity_type="example.Session",
        key=[{"field": "id", "type": "string"}],
        contract_fingerprint=application.schema.fingerprint,
    )


def test_interrupted_import_is_atomic_and_orphan_is_only_reported(
    memory_store: MemoryStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application(memory_store, tmp_path / "evidence")
    source = _write(
        tmp_path / "sessions.jsonl",
        [{"id": f"s{index}", "status": "ok"} for index in range(3)],
    )
    digest = sha256(source.read_bytes()).hexdigest()
    before = application.memory_store.snapshot_records()

    def interrupted(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
        iterator = original_iter_jsonl(path)
        yield next(iterator)
        raise RuntimeError("forced interruption")

    monkeypatch.setattr("analytical_memory.adapters.sqlite.iter_jsonl", interrupted)
    monkeypatch.setattr(application.evidence_store, "remove", lambda _digest: False)

    with pytest.raises(RuntimeError, match="forced interruption"):
        _import(application, source)

    after = application.memory_store.snapshot_records()
    assert after == before
    assert application.memory_store.integrity()["ok"] is True
    audit = application.evidence_audit()
    assert [item["digest"] for item in audit["orphans"]] == [digest]
    object_path = tmp_path / "evidence" / "objects" / "sha256" / digest[:2] / digest
    assert object_path.is_file()


def test_snapshot_roundtrip_reproduces_ordered_query_and_ontology(
    tmp_path: Path,
) -> None:
    source = _application(
        SqliteMemoryStore(tmp_path / "source.db"), tmp_path / "source-evidence"
    )
    _import(
        source,
        _write(
            tmp_path / "sessions.jsonl",
            [
                {"id": "s2", "status": "failed"},
                {"id": "s1", "status": "completed"},
            ],
        ),
    )
    query = {
        "query_ir_version": "1",
        "match": {"nodes": [{"type": "example.Session", "as": "session"}]},
        "return": [
            {"field": "session.id"},
            {"field": "session.status"},
        ],
        "order_by": [{"field": "session.status", "direction": "asc"}],
    }
    expected_query = source.execute_query(query)
    expected_ontology = source.ontology()["ontology_fingerprint"]
    snapshot = tmp_path / "snapshot.zip"
    manifest = source.snapshot_create(snapshot, created_at="2026-01-01T00:00:00Z")
    assert source.snapshot_verify(snapshot)["snapshot_id"] == manifest["snapshot_id"]

    restored = MemoryApplication(
        SqliteMemoryStore(tmp_path / "restored.db"),
        FileEvidenceStore(tmp_path / "restored-evidence"),
        load_schema(),
    )
    restored.snapshot_import(snapshot)

    assert restored.execute_query(query) == expected_query
    assert restored.ontology()["ontology_fingerprint"] == expected_ontology


def test_evidence_corruption_reports_object_and_fragment_without_content_changes(
    tmp_path: Path,
) -> None:
    application = _application(
        SqliteMemoryStore(tmp_path / "memory.db"), tmp_path / "evidence"
    )
    imported = _import(
        application,
        _write(tmp_path / "sessions.jsonl", [{"id": "s1", "status": "ok"}]),
    )
    content_tables = (
        "node",
        "node_attribute",
        "relation",
        "metric",
        "evidence_object",
        "evidence_fragment",
        "observed_field",
    )
    before = application.memory_store.snapshot_records()
    digest = str(imported["evidence_digest"])
    object_path = tmp_path / "evidence" / "objects" / "sha256" / digest[:2] / digest
    data = object_path.read_bytes()
    object_path.write_bytes(bytes([data[0] ^ 1]) + data[1:])

    result = application.evidence_verify(digest)

    assert result["verification"] == "corrupt"
    assert result["fragments"]
    assert all(item["outcome"] == "corrupt" for item in result["fragments"])
    after = application.memory_store.snapshot_records()
    for table in content_tables:
        assert after[table] == before[table]
    assert len(after["evidence_verification"]) > len(before["evidence_verification"])


def test_unknown_sqlite_schema_version_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "future.db"
    store = SqliteMemoryStore(database)
    store.initialize()
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 7")

    with pytest.raises(StoreNotInitializedError, match="unsupported SQLite"):
        store.initialize()


def test_unknown_postgresql_schema_version_is_rejected(
    postgres_store: MemoryStore,
) -> None:
    postgres_store.initialize()
    connection = cast(Any, postgres_store)._connect()
    with connection:
        connection.execute(
            "INSERT INTO schema_migration "
            "(backend_profile, version, checksum, target_fingerprint, "
            "applied_at, tool_version) VALUES (?, 7, 'future', 'future', "
            "'2026-01-01T00:00:00Z', 'future')",
            ("postgresql",),
        )

    with pytest.raises(StoreNotInitializedError, match="ledger does not match"):
        postgres_store.initialize()
