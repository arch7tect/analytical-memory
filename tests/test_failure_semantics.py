from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.application import MemoryApplication
from analytical_memory.domain import (
    BatchPlan,
    EmbeddingProfileRecord,
    EmbeddingRecord,
    MemoryStoreStatus,
    StoredBatch,
)
from analytical_memory.errors import (
    BatchValidationError,
    IdempotencyConflictError,
    SchemaChangedError,
)
from analytical_memory.ports import MemoryStore

from .conftest import ApplicationFixture


def _rewrite_batch(path: Path, changes: dict[str, Any]) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    value.update(changes)
    path.write_text(json.dumps(value), encoding="utf-8")


def _batch_count(database: Path) -> int:
    with sqlite3.connect(database) as connection:
        return int(
            connection.execute("SELECT COUNT(*) FROM ingestion_batch").fetchone()[0]
        )


def _all_table_counts(database: Path) -> dict[str, int]:
    tables = (
        "ingestion_batch",
        "source",
        "analytical_run",
        "node",
        "node_attribute",
        "assertion",
        "evidence_object",
        "evidence_acquisition",
        "evidence_derivation",
        "evidence_fragment",
        "evidence_binding",
        "evidence_location",
        "evidence_verification",
        "evidence_retirement",
        "relation",
        "metric",
        "search_document",
    )
    with sqlite3.connect(database) as connection:
        return {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in tables
        }


def test_stale_schema_fingerprint_is_rejected_before_writes(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    _rewrite_batch(fixture.batch_path, {"schema_fingerprint": "0" * 64})

    with pytest.raises(SchemaChangedError, match="schema_changed"):
        fixture.application.apply(fixture.batch_path)

    assert _batch_count(fixture.database) == 0
    assert list(fixture.evidence_store.root.rglob("?" * 64)) == []


def test_idempotency_key_rejects_changed_input(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    fixture.application.apply(fixture.batch_path)
    original_count = _batch_count(fixture.database)
    _rewrite_batch(fixture.batch_path, {"recorded_at": "2000-01-02T00:00:00Z"})

    with pytest.raises(IdempotencyConflictError, match="different input"):
        fixture.application.apply(fixture.batch_path)

    assert _batch_count(fixture.database) == original_count


def test_invalid_batch_is_rejected_before_evidence_put(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    document["nodes"][0]["attributes"][0]["assertions"][0]["stance"] = "invalid"
    fixture.batch_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BatchValidationError, match="stance is invalid"):
        fixture.application.apply(fixture.batch_path)

    assert set(_all_table_counts(fixture.database).values()) == {0}
    assert list(fixture.evidence_store.root.rglob("?" * 64)) == []


class FailingMemoryStore(MemoryStore):
    def initialize(self) -> None:
        return None

    def get_batch(self, idempotency_key: str) -> StoredBatch | None:
        return None

    def apply(self, plan: BatchPlan) -> dict[str, Any]:
        raise RuntimeError("synthetic database failure")

    def current_facts(self) -> list[dict[str, Any]]:
        return []

    def current_slots(self) -> list[dict[str, Any]]:
        return []

    def current_relations(self) -> list[dict[str, Any]]:
        return []

    def traverse_relations(
        self,
        start_node_id: str,
        *,
        relation_types: list[str] | None,
        direction: str,
        max_depth: int,
        limit: int,
        states: list[str],
    ) -> dict[str, Any]:
        raise AssertionError("not used")

    def get_node(self, node_id: str) -> dict[str, Any]:
        raise AssertionError("not used")

    def current_metric(
        self, definition_version: str, dimensions_json: str
    ) -> dict[str, Any] | None:
        return None

    def search_text(self, query: str, limit: int) -> dict[str, Any]:
        return {"results": [], "coverage": {}}

    def explain_attribute(self, attribute_id: str) -> dict[str, Any]:
        raise AssertionError("not used")

    def explain_relation(self, relation_id: str) -> dict[str, Any]:
        raise AssertionError("not used")

    def explain_metric(self, metric_id: str) -> dict[str, Any]:
        raise AssertionError("not used")

    def evidence_catalog(
        self, limit: int, digest: str | None = None
    ) -> tuple[list[dict[str, Any]], bool]:
        return [], False

    def record_evidence_check(
        self,
        digest: str,
        *,
        availability: str,
        verification: str,
        byte_size: int | None,
        checked_at: str,
        method: str,
    ) -> dict[str, Any]:
        raise AssertionError("not used")

    def record_fragment_check(
        self,
        fragment_id: str,
        *,
        digest: str,
        outcome: str,
        byte_size: int | None,
        checked_at: str,
        method: str,
    ) -> None:
        raise AssertionError("not used")

    def record_artifact_check(
        self,
        target_kind: str,
        target_id: str,
        *,
        digest: str,
        outcome: str,
        byte_size: int | None,
        checked_at: str,
        method: str,
    ) -> None:
        raise AssertionError("not used")

    def retention_report(self, as_of: str) -> list[dict[str, Any]]:
        return []

    def record_retirement(
        self, digest: str, *, plan_id: str, reason: str, retired_at: str
    ) -> None:
        raise AssertionError("not used")

    def record_retirements(
        self,
        digests: list[str],
        *,
        plan_id: str,
        reason: str,
        retired_at: str,
    ) -> None:
        raise AssertionError("not used")

    def snapshot_records(self) -> dict[str, list[dict[str, Any]]]:
        return {}

    def import_snapshot_records(
        self, records: dict[str, list[dict[str, Any]]]
    ) -> dict[str, int]:
        raise AssertionError("not used")

    def integrity(self) -> dict[str, Any]:
        return {"ok": False}

    def status(self) -> MemoryStoreStatus:
        return MemoryStoreStatus(backend="failing", initialized=True, schema_version=1)

    def evidence_digests(self, limit: int) -> tuple[list[str], bool]:
        return [], False

    def put_embedding_profile(self, profile: EmbeddingProfileRecord) -> None:
        raise AssertionError("not used")

    def get_embedding_profile(self, profile_id: str) -> dict[str, Any]:
        raise AssertionError("not used")

    def set_embedding_profile_status(
        self, profile_id: str, status: str, last_error: str | None
    ) -> None:
        raise AssertionError("not used")

    def embedding_documents(self, profile_id: str) -> list[dict[str, Any]]:
        raise AssertionError("not used")

    def put_embedding_records(self, records: list[EmbeddingRecord]) -> None:
        raise AssertionError("not used")

    def clear_embedding_records(self, profile_id: str) -> int:
        raise AssertionError("not used")

    def embedding_candidates(
        self,
        profile_id: str,
        *,
        namespace: str | None,
        node_type: str | None,
        privacy_ceiling: str | None,
    ) -> list[dict[str, Any]]:
        raise AssertionError("not used")

    def embedding_coverage(self, profile_id: str) -> dict[str, int]:
        raise AssertionError("not used")


def test_database_failure_leaves_addressable_unreferenced_evidence(
    application_fixture: ApplicationFixture,
    tmp_path: Path,
) -> None:
    fixture = application_fixture
    evidence_store = FileEvidenceStore(tmp_path / "failure-evidence")
    application = MemoryApplication(
        FailingMemoryStore(), evidence_store, fixture.schema
    )

    with pytest.raises(RuntimeError, match="synthetic database failure"):
        application.apply(fixture.batch_path)

    plan = application.plan(fixture.batch_path)
    status = evidence_store.stat(plan.evidence.object.digest)
    assert status.availability == "present"
    assert status.verification == "verified"


def test_sqlite_failure_rolls_back_every_canonical_row(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    plan = fixture.application.plan(fixture.batch_path)
    fixture.evidence_store.put(plan.evidence.source_path, plan.evidence.object)
    invalid_assertion = replace(plan.assertions[0], stance="invalid")
    invalid_plan = replace(plan, assertions=(invalid_assertion, *plan.assertions[1:]))

    with pytest.raises(BatchValidationError, match="storage constraints"):
        fixture.memory_store.apply(invalid_plan)

    assert set(_all_table_counts(fixture.database).values()) == {0}
    status = fixture.evidence_store.stat(plan.evidence.object.digest)
    assert status.availability == "present"
    assert status.verification == "verified"


def test_cross_batch_cardinality_conflict_is_a_domain_error(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    fixture.application.apply(fixture.batch_path)
    document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    document["idempotency_key"] = "quickstart-cardinality-conflict"
    document["nodes"][0]["attributes"][0]["cardinality"] = "multi"
    fixture.batch_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BatchValidationError, match="cardinality conflict"):
        fixture.application.apply(fixture.batch_path)
