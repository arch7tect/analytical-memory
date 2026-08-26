from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.api import MemoryAPI
from analytical_memory.application import MemoryApplication
from analytical_memory.canonical import sha256_bytes
from analytical_memory.errors import (
    BatchValidationError,
    RetentionBlockedError,
    SnapshotError,
)
from analytical_memory.evidence import select_fragment

from .conftest import ApplicationFixture


@pytest.mark.parametrize(
    ("data", "locator", "expected"),
    [
        (b"abcdef", {"kind": "whole_object"}, b"abcdef"),
        (b"abcdef", {"kind": "byte_range", "start": 1, "end": 4}, b"bcd"),
        (
            b"one\ntwo\nthree\n",
            {"kind": "line_range", "start_line": 2, "end_line": 3},
            b"two\nthree\n",
        ),
        (
            b'{ "a": [1, {"b": true}] }',
            {
                "kind": "structured",
                "input_format": "json",
                "pointer": "/a/1/b",
            },
            b"true",
        ),
        (
            b'{"id":1,"v":"a"}\n{"id":2,"v":"b"}\n',
            {
                "kind": "record_key",
                "input_format": "jsonl",
                "key_field": "id",
                "key_value": 2,
            },
            b'{"id":2,"v":"b"}\n',
        ),
        (
            b'[{"t":"2000-01-01T00:00:00Z","v":1},{"t":"2000-01-02T00:00:00Z","v":2}]',
            {
                "kind": "time_interval",
                "input_format": "json",
                "timestamp_field": "t",
                "start": "2000-01-02T00:00:00Z",
                "end": "2000-01-03T00:00:00Z",
            },
            b'{"t":"2000-01-02T00:00:00Z","v":2}\n',
        ),
        (
            bytes(range(16)),
            {
                "kind": "sample_interval",
                "start_sample": 1,
                "end_sample": 3,
                "sample_rate": 8000,
                "channels": 1,
                "sample_format": "unsigned-integer",
                "bit_width": 8,
                "byte_order": "little",
                "interleaved": True,
            },
            bytes([1, 2]),
        ),
        (
            bytes([0, 1, 2, 3, 10, 11, 12, 13]),
            {
                "kind": "sample_interval",
                "start_sample": 1,
                "end_sample": 3,
                "sample_rate": 8000,
                "channels": 2,
                "sample_format": "unsigned-integer",
                "bit_width": 8,
                "byte_order": "little",
                "interleaved": False,
            },
            bytes([1, 2, 11, 12]),
        ),
    ],
)
def test_fragment_locators_are_deterministic(
    data: bytes, locator: dict[str, object], expected: bytes
) -> None:
    first = select_fragment(data, locator)
    second = select_fragment(data, json.loads(json.dumps(locator)))

    assert first.locator == second.locator
    assert first.addressed_bytes == second.addressed_bytes
    assert first.extracted_bytes == second.extracted_bytes == expected
    assert sha256_bytes(first.extracted_bytes) == sha256_bytes(second.extracted_bytes)


def test_canonical_source_locator_rejects_machine_paths(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    document["source"]["locator"] = "/private/machine/source.txt"
    fixture.batch_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BatchValidationError, match="absolute machine path"):
        fixture.application.plan(fixture.batch_path)

    with pytest.raises(BatchValidationError, match="unknown keys"):
        select_fragment(
            b'{"a": 1}',
            {
                "kind": "structured",
                "input_format": "json",
                "ponter": "/a",
            },
        )


@pytest.mark.parametrize(
    ("data", "locator"),
    [
        (b"abcdef", {"kind": "whole_object"}),
        (b"abcdef", {"kind": "byte_range", "start": 1, "end": 4}),
        (
            b"one\ntwo\n",
            {"kind": "line_range", "start_line": 1, "end_line": 1},
        ),
        (
            b'{"a":{"b":1}}',
            {
                "kind": "structured",
                "input_format": "json",
                "pointer": "/a",
            },
        ),
        (
            b'{"id":1}\n{"id":2}\n',
            {
                "kind": "record_key",
                "input_format": "jsonl",
                "key_field": "id",
                "key_value": 2,
            },
        ),
        (
            b'[{"t":"2000-01-01T00:00:00Z"}]',
            {
                "kind": "time_interval",
                "input_format": "json",
                "timestamp_field": "t",
                "start": "2000-01-01T00:00:00Z",
                "end": "2000-01-02T00:00:00Z",
            },
        ),
        (
            bytes(range(16)),
            {
                "kind": "sample_interval",
                "start_sample": 1,
                "end_sample": 3,
                "sample_rate": 8000,
                "channels": 1,
                "sample_format": "unsigned-integer",
                "bit_width": 8,
                "byte_order": "little",
                "interleaved": True,
            },
        ),
    ],
)
def test_typed_explanation_accepts_every_locator(
    application_fixture: ApplicationFixture,
    data: bytes,
    locator: dict[str, object],
) -> None:
    fixture = application_fixture
    fixture.batch_path.parent.joinpath("evidence.txt").write_bytes(data)
    document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    document["evidence"]["fragment"] = locator
    fixture.batch_path.write_text(json.dumps(document), encoding="utf-8")
    fixture.application.initialize()
    plan = fixture.application.plan(fixture.batch_path)
    fixture.application.apply(fixture.batch_path)

    explanation = MemoryAPI(fixture.application).explain(plan.attributes[0].id)
    binding = explanation.assertions[0].evidence[0]
    assert binding.locator_kind == locator["kind"]
    assert binding.locator.kind == locator["kind"]


def test_structured_input_is_materialized_and_audited(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    fixture.batch_path.parent.joinpath("evidence.txt").write_text(
        '{ "items" : [ { "id" : 1 }, { "id" : 2 } ] }', encoding="utf-8"
    )
    document["evidence"]["media_type"] = "application/json"
    document["evidence"]["fragment"] = {
        "input_format": "json",
        "kind": "structured",
        "pointer": "/items/1",
    }
    fixture.batch_path.write_text(json.dumps(document), encoding="utf-8")
    fixture.application.initialize()
    plan = fixture.application.plan(fixture.batch_path)
    fixture.application.apply(fixture.batch_path)

    assert len(plan.evidence.materialized_objects) == 1
    assert len(plan.evidence.derivations) == 1
    derived = plan.evidence.materialized_objects[0][0]
    assert plan.evidence.fragment.evidence_object_id == derived.id
    audit = fixture.application.evidence_audit(checked_at="2000-01-03T00:00:00.000000Z")
    fragment_checks = [
        fragment for result in audit["results"] for fragment in result["fragments"]
    ]
    assert fragment_checks == [
        {
            "expected_digest": plan.evidence.fragment.digest,
            "fragment_id": plan.evidence.fragment.id,
            "outcome": "verified",
            "reproduced_digest": plan.evidence.fragment.digest,
        }
    ]
    with sqlite3.connect(fixture.database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM evidence_verification").fetchone()[
                0
            ]
            == 5
        )


def test_acquisition_privacy_is_monotonic_and_history_is_append_only(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    initial_document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    initial_document["source"]["privacy_class"] = "private"
    fixture.batch_path.write_text(json.dumps(initial_document), encoding="utf-8")
    first = fixture.application.apply(fixture.batch_path)
    digest = str(first["result"]["evidence_digest"])
    assert fixture.application.evidence_status(digest)["effective_privacy"] == "private"
    document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    document["idempotency_key"] = "quickstart-restricted-acquisition"
    document["evidence"]["privacy_class"] = "restricted"
    fixture.batch_path.write_text(json.dumps(document), encoding="utf-8")
    fixture.application.apply(fixture.batch_path)
    fixture.application.evidence_verify(
        digest, checked_at="2000-01-04T00:00:00.000000Z"
    )

    status = fixture.application.evidence_status(digest)
    assert status["effective_privacy"] == "restricted"
    with sqlite3.connect(fixture.database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM evidence_acquisition").fetchone()[
                0
            ]
            == 2
        )
        assert (
            connection.execute(
                "SELECT privacy_class FROM evidence_object WHERE digest = ?", (digest,)
            ).fetchone()[0]
            == "restricted"
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM evidence_verification").fetchone()[
                0
            ]
            == 3
        )


def test_audit_persists_missing_location_without_losing_verified_history(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    applied = fixture.application.apply(fixture.batch_path)
    digest = str(applied["result"]["evidence_digest"])
    fixture.evidence_store.object_path(digest).unlink()

    result = fixture.application.evidence_audit(
        checked_at="2000-01-05T00:00:00.000000Z"
    )
    assert result["results"][0]["availability"] == "missing"
    with sqlite3.connect(fixture.database) as connection:
        location = connection.execute(
            "SELECT availability FROM evidence_location"
        ).fetchone()[0]
        outcomes = [
            row[0]
            for row in connection.execute(
                "SELECT outcome FROM evidence_verification ORDER BY checked_at"
            )
        ]
    assert location == "missing"
    assert outcomes == ["verified", "missing"]


def test_retention_requires_immutable_plan_and_blocks_active_requirements(
    application_fixture: ApplicationFixture,
    tmp_path: Path,
) -> None:
    fixture = application_fixture
    document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    document["evidence"]["retention"] = {"required": True}
    fixture.batch_path.write_text(json.dumps(document), encoding="utf-8")
    fixture.application.initialize()
    applied = fixture.application.apply(fixture.batch_path)
    digest = str(applied["result"]["evidence_digest"])
    report = fixture.application.retention_report(as_of="2001-01-01T00:00:00.000000Z")
    assert report["objects"][0]["retention_state"] == "active"

    plan_path = tmp_path / "blocked-plan.json"
    plan = fixture.application.retention_plan(
        plan_path, created_at="2001-01-01T00:00:00.000000Z"
    )
    assert plan["objects"] == []
    with pytest.raises(FileExistsError):
        fixture.application.retention_plan(plan_path)
    with pytest.raises(RetentionBlockedError):
        fixture.memory_store.record_retirement(
            digest,
            plan_id="blocked",
            reason="test",
            retired_at="2001-01-01T00:00:00.000000Z",
        )


def test_retirement_records_tombstone_before_store_removal(
    application_fixture: ApplicationFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    applied = fixture.application.apply(fixture.batch_path)
    digest = str(applied["result"]["evidence_digest"])
    plan_path = tmp_path / "retirement-failure-plan.json"
    plan = fixture.application.retention_plan(
        plan_path,
        digests=[digest],
        created_at="2001-01-01T00:00:00Z",
    )

    def fail_removal(_: str) -> bool:
        raise OSError("synthetic removal failure")

    monkeypatch.setattr(fixture.evidence_store, "retire", fail_removal)
    result = fixture.application.retention_retire(
        plan_path,
        confirmation=str(plan["plan_id"]),
        retired_at="2001-01-02T00:00:00Z",
    )

    assert result["outcomes"] == [
        {
            "digest": digest,
            "error": "synthetic removal failure",
            "store_copy": "removal_failed",
            "tombstone": "recorded",
        }
    ]
    assert fixture.evidence_store.object_path(digest).is_file()
    with sqlite3.connect(fixture.database) as connection:
        retirement_count = connection.execute(
            "SELECT COUNT(*) FROM evidence_retirement WHERE digest = ?", (digest,)
        ).fetchone()[0]
        location = connection.execute(
            "SELECT availability FROM evidence_location"
        ).fetchone()[0]
    assert retirement_count == 1
    assert location == "missing"


def test_snapshot_restores_present_objects_tombstones_and_queries(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
    tmp_path: Path,
) -> None:
    source = application_fixture
    source.application.initialize()
    first = source.application.apply(source.batch_path)
    source.application.apply(querying_batch_path)
    retired_digest = str(first["result"]["evidence_digest"])
    retention_plan_path = tmp_path / "retention-plan.json"
    retention_plan = source.application.retention_plan(
        retention_plan_path,
        digests=[retired_digest],
        created_at="2001-01-01T00:00:00.000000Z",
    )
    source.application.retention_retire(
        retention_plan_path,
        confirmation=str(retention_plan["plan_id"]),
        retired_at="2001-01-02T00:00:00.000000Z",
    )
    assert source.batch_path.parent.joinpath("evidence.txt").is_file()
    source_facts = source.application.current_facts()
    source_slots = source.application.current_slots()
    snapshot_path = tmp_path / "memory.snapshot.zip"
    created = source.application.snapshot_create(
        snapshot_path, created_at="2001-01-03T00:00:00.000000Z"
    )
    assert (
        source.application.snapshot_verify(snapshot_path)["snapshot_id"]
        == created["snapshot_id"]
    )

    target_database = tmp_path / "target" / "memory.db"
    target_evidence = FileEvidenceStore(tmp_path / "target" / "evidence")
    target = MemoryApplication(
        SqliteMemoryStore(target_database), target_evidence, source.schema
    )
    imported = target.snapshot_import(snapshot_path)

    assert imported["snapshot_id"] == created["snapshot_id"]
    assert target.current_facts() == source_facts
    assert target.current_slots() == source_slots
    assert target.evidence_status(retired_digest)["retired"] is True
    assert target.evidence_status(retired_digest)["availability"] == "missing"
    querying_digest = source.application.plan(
        querying_batch_path
    ).evidence.object.digest
    assert target.evidence_status(querying_digest)["verification"] == "verified"
    assert target.search_text("connected")["results"]
    retired_attribute = str(first["result"]["attribute_ids"][0])
    present_attribute = source.application.plan(querying_batch_path).attributes[0].id
    assert (
        target.explain(retired_attribute)["assertions"][0]["evidence"][0]["status"][
            "availability"
        ]
        == "missing"
    )
    assert (
        target.explain(present_attribute)["assertions"][0]["evidence"][0]["status"][
            "verification"
        ]
        == "verified"
    )
    with zipfile.ZipFile(snapshot_path) as archive:
        records = archive.read("records.json").decode("utf-8")
    assert str(source.batch_path.parent.resolve()) not in records


def test_failed_snapshot_verification_or_import_preserves_existing_state(
    application_fixture: ApplicationFixture,
    tmp_path: Path,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    fixture.application.apply(fixture.batch_path)
    before = fixture.memory_store.snapshot_records()
    invalid = tmp_path / "invalid.snapshot"
    invalid.write_bytes(b"not-a-snapshot")

    with pytest.raises(SnapshotError):
        fixture.application.snapshot_import(invalid)
    assert fixture.memory_store.snapshot_records() == before

    valid = tmp_path / "valid.snapshot.zip"
    fixture.application.snapshot_create(valid, created_at="2001-01-01T00:00:00Z")
    tampered = tmp_path / "tampered.snapshot.zip"
    with (
        zipfile.ZipFile(valid) as source_archive,
        zipfile.ZipFile(tampered, "w") as target_archive,
    ):
        for info in source_archive.infolist():
            data = source_archive.read(info.filename)
            if info.filename.startswith("objects/"):
                data += b"tampered"
            target_archive.writestr(info.filename, data)
    with pytest.raises(SnapshotError, match="failed verification"):
        fixture.application.snapshot_import(tampered)
    assert fixture.memory_store.snapshot_records() == before

    sanitized = tmp_path / "sanitized.json"
    fixture.application.sanitized_export(
        sanitized, created_at="2001-01-01T00:00:00.000000Z"
    )
    with pytest.raises(SnapshotError):
        fixture.application.snapshot_import(sanitized)
    assert fixture.memory_store.snapshot_records() == before


def test_sanitized_export_applies_privacy_ceiling(
    application_fixture: ApplicationFixture,
    tmp_path: Path,
) -> None:
    fixture = application_fixture
    document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    document["nodes"][0]["attributes"][0]["privacy_class"] = "restricted"
    fixture.batch_path.write_text(json.dumps(document), encoding="utf-8")
    fixture.application.initialize()
    fixture.application.apply(fixture.batch_path)
    destination = tmp_path / "public-export.json"

    exported = fixture.application.sanitized_export(
        destination,
        privacy_ceiling="public",
        created_at="2001-01-01T00:00:00Z",
    )

    assert exported["artifact_kind"] == "sanitized-export"
    assert exported["restore_compatible"] is False
    assert all(item["privacy_class"] == "public" for item in exported["facts"])
    assert len(exported["facts"]) == 3


def test_snapshot_import_defers_assertion_self_references(
    application_fixture: ApplicationFixture,
    tmp_path: Path,
) -> None:
    source = application_fixture
    source.application.initialize()
    source.application.apply(source.batch_path)
    plan = source.application.plan(source.batch_path)
    predecessor = plan.assertions[0]
    successor_id = "00000000-0000-0000-0000-000000000001"
    with sqlite3.connect(source.database) as connection:
        connection.execute(
            """
            INSERT INTO assertion VALUES (
                ?, 'node_attribute', ?, ?, NULL, 'supports', 'observed', 1.0,
                'reviewed', '2000-01-02T00:00:00Z', NULL,
                '2000-01-02T00:00:00Z', 'supersession-test', ?, ?, ?,
                'active', 'supersession-test-stable-key', 2
            )
            """,
            (
                successor_id,
                predecessor.target_id,
                predecessor.attribute_id,
                predecessor.source_id,
                predecessor.run_id,
                predecessor.id,
            ),
        )
    snapshot = tmp_path / "supersession.snapshot.zip"
    source.application.snapshot_create(snapshot, created_at="2001-01-01T00:00:00Z")
    target = MemoryApplication(
        SqliteMemoryStore(tmp_path / "supersession-target.db"),
        FileEvidenceStore(tmp_path / "supersession-evidence"),
        source.schema,
    )

    target.snapshot_import(snapshot)
    explanation = target.explain(str(predecessor.attribute_id))
    effective = [
        item["assertion_id"] for item in explanation["assertions"] if item["effective"]
    ]
    assert effective == [successor_id]
