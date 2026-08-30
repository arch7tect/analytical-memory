from __future__ import annotations

import json
import os
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest
from mcp import Client, StdioServerParameters
from mcp.types import TextContent
from pydantic import ValidationError

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.api_models import QUERY_OPERATORS, QueryIRDocument
from analytical_memory.application import MemoryApplication
from analytical_memory.cli import main
from analytical_memory.domain import (
    EmbeddingBatch,
    EmbeddingProviderInfo,
    EvidenceObjectRecord,
)
from analytical_memory.errors import (
    AmbiguousTargetError,
    ImportValidationError,
    JoinConflictError,
    OntologyConflictError,
    ProhibitedContentError,
    QueryValidationError,
    RetentionBlockedError,
    SchemaChangedError,
    error_code_registry,
)
from analytical_memory.ports import EmbeddingProvider, MemoryStore
from analytical_memory.query_ir import parse_query_ir, query_ir_contract_document
from analytical_memory.resources import resource_path
from analytical_memory.schema_contract import default_schema_path, load_schema

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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
            (1.0, 0.0, 0.0) if "failed" in text else (0.0, 1.0, 0.0) for text in texts
        )
        return EmbeddingBatch(vectors=vectors, response_model="fixture-v1")


@pytest.fixture
def m5(
    tmp_path: Path, memory_store: MemoryStore
) -> tuple[MemoryApplication, Path | None, Path]:
    evidence_root = tmp_path / "evidence"
    application = MemoryApplication(
        memory_store,
        FileEvidenceStore(evidence_root),
        load_schema(default_schema_path()),
    )
    application.initialize()
    database = (
        memory_store.database if isinstance(memory_store, SqliteMemoryStore) else None
    )
    return application, database, evidence_root


def _write(path: Path, records: list[dict[str, Any]]) -> Path:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _import(
    application: MemoryApplication,
    path: Path,
    entity_type: str,
    key: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return application.jsonl_import(
        path,
        entity_type=entity_type,
        key=key or [{"field": "id", "type": "string"}],
        contract_fingerprint=application.schema.fingerprint,
    )


def _tool_json(result: Any) -> dict[str, Any]:
    if result.structured_content is not None:
        value = dict(result.structured_content)
        nested = value.get("result")
        return dict(nested) if isinstance(nested, dict) else value
    blocks = [block.text for block in result.content if hasattr(block, "text")]
    value = json.loads("".join(blocks))
    if not isinstance(value, dict):
        raise AssertionError("tool result must be an object")
    return value


def _resource_json(result: Any) -> dict[str, Any]:
    value = json.loads(str(result.contents[0].text))
    if not isinstance(value, dict):
        raise AssertionError("resource must contain an object")
    return value


def test_ontology_namespaces_and_descriptions_are_replaceable(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    contract = application.schema.fingerprint
    namespace_result = application.declare_namespace(
        "calls.voice",
        "Voice call records.",
        contract_fingerprint=contract,
    )
    namespace = namespace_result["document"]["namespaces"][0]
    assert namespace["name"] == "calls.voice"
    assert namespace["description"] == "Voice call records."
    assert namespace["declared"] is True
    assert namespace["provenance"]["fragment_id"] is not None
    assert namespace_result["document"]["entities"] == []

    declared = application.declare_entity(
        "calls.voice.Session",
        description="One completed or attempted call.",
        fields={
            "id": {
                "description": "Stable session identifier.",
                "type": "string",
                "required": True,
                "nullable": False,
            }
        },
        contract_fingerprint=contract,
    )
    entity = declared["document"]["entities"][0]
    assert entity["description"] == "One completed or attempted call."
    assert entity["fields"]["id"]["description"] == "Stable session identifier."
    described_fingerprint = declared["ontology_fingerprint"]

    cleared = application.declare_entity(
        "calls.voice.Session",
        fields={"id": {"type": "string", "required": True, "nullable": False}},
        contract_fingerprint=contract,
    )
    entity = cleared["document"]["entities"][0]
    assert entity["description"] is None
    assert entity["fields"]["id"]["description"] is None
    assert cleared["ontology_fingerprint"] != described_fingerprint

    filtered = application.ontology("calls.voice")["document"]
    assert [item["name"] for item in filtered["namespaces"]] == ["calls.voice"]

    _import(
        application,
        _write(tmp_path / "sessions.jsonl", [{"id": "s1", "customer_id": "c1"}]),
        "calls.voice.Session",
    )
    _import(
        application,
        _write(tmp_path / "customers.jsonl", [{"id": "c1"}]),
        "crm.Customer",
    )
    arguments = {
        "name": "session-customer",
        "relation": "BELONGS_TO",
        "from_": {"type": "calls.voice.Session", "fields": ["customer_id"]},
        "to": {"type": "crm.Customer", "fields": ["id"]},
        "contract_fingerprint": contract,
    }
    first = application.materialize_join(
        **arguments,
        description="Links a call to its customer.",
        idempotency_key="description-join-1",
    )
    second = application.materialize_join(
        **arguments,
        description="Current customer link.",
        idempotency_key="description-join-2",
    )
    relation = application.ontology()["document"]["relations"][0]
    assert relation["description"] == "Current customer link."
    assert relation["statistics"]["active_edges"] == 1
    assert first["definition_hash"] == second["definition_hash"]
    assert second["created_relations"] == 0
    parent_view = application.ontology("calls")["document"]
    assert [item["type"] for item in parent_view["entities"]] == ["calls.voice.Session"]
    assert parent_view["statistics"] == {
        "active_relations": 1,
        "attributes": 2,
        "nodes": 1,
    }


def test_typed_composite_and_integer_import_keys(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    composite_key = [
        {"field": "tenant", "type": "string"},
        {"field": "code", "type": "number"},
    ]
    created = _import(
        application,
        _write(
            tmp_path / "composite.jsonl",
            [
                {"tenant": "t1", "code": 1, "value": "first"},
                {"tenant": "t2", "code": 1, "value": "second"},
                {"tenant": "t1", "code": 2, "value": "third"},
            ],
        ),
        "calls.CompositeSession",
        composite_key,
    )
    assert created["created_nodes"] == 3
    updated = _import(
        application,
        _write(
            tmp_path / "composite-patch.jsonl",
            [{"tenant": "t1", "code": 1, "value": "updated"}],
        ),
        "calls.CompositeSession",
        composite_key,
    )
    assert updated["created_nodes"] == 0
    assert updated["updated_nodes"] == 1

    with pytest.raises(ImportValidationError, match="expected number"):
        _import(
            application,
            _write(
                tmp_path / "wrong-composite-type.jsonl",
                [{"tenant": "t1", "code": "1"}],
            ),
            "calls.CompositeSession",
            composite_key,
        )

    integer_key = [{"field": "code", "type": "integer"}]
    integer_created = _import(
        application,
        _write(tmp_path / "integer.jsonl", [{"code": 7, "value": "first"}]),
        "calls.IntegerSession",
        integer_key,
    )
    integer_updated = _import(
        application,
        _write(
            tmp_path / "integer-patch.jsonl",
            [{"code": 7, "value": "updated"}],
        ),
        "calls.IntegerSession",
        integer_key,
    )
    assert integer_created["created_nodes"] == 1
    assert integer_updated["created_nodes"] == 0
    assert integer_updated["updated_nodes"] == 1
    assert len(application.memory_store.snapshot_records()["node"]) == 4


def test_composite_import_key_ambiguity_rolls_back(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    _import(
        application,
        _write(
            tmp_path / "ambiguous-composite-source.jsonl",
            [
                {"id": "a", "tenant": "t1", "code": 1},
                {"id": "b", "tenant": "t1", "code": 1},
            ],
        ),
        "calls.CompositeSession",
    )
    before = application.memory_store.snapshot_records()
    with pytest.raises(ImportValidationError, match="ambiguous import key"):
        _import(
            application,
            _write(
                tmp_path / "ambiguous-composite-patch.jsonl",
                [{"tenant": "t1", "code": 1, "value": "ambiguous"}],
            ),
            "calls.CompositeSession",
            [
                {"field": "tenant", "type": "string"},
                {"field": "code", "type": "number"},
            ],
        )
    after = application.memory_store.snapshot_records()
    assert after["node"] == before["node"]
    assert after["node_attribute"] == before["node_attribute"]


def test_declaration_import_patch_replay_and_ontology(m5: tuple[Any, ...]) -> None:
    application, _, _ = m5
    fingerprint = application.schema.fingerprint
    before = application.declare_entity(
        "calls.Session",
        fields={
            "id": {"type": "string", "required": True, "nullable": False},
            "status": {"type": "string", "nullable": True},
        },
        contract_fingerprint=fingerprint,
    )
    declared_entity = before["document"]["entities"][0]
    assert declared_entity["provenance"]["fragment_id"] is not None
    source = _write(
        Path(application.evidence_store.root).parent / "sessions.jsonl",
        [
            {"id": "s1", "status": "completed"},
            {"id": "s2", "status": "failed", "duration": 42},
        ],
    )
    first = _import(application, source, "calls.Session")
    replay = _import(application, source, "calls.Session")
    assert first["created_nodes"] == 2
    assert replay["replayed"] is True
    assert replay["contract_fingerprint"] == fingerprint

    patch = _write(
        source.with_name("session-patch.jsonl"),
        [{"id": "s2", "status": None}],
    )
    updated = _import(application, patch, "calls.Session")
    assert updated["updated_nodes"] == 1
    ontology = application.ontology()["document"]
    session = next(
        item for item in ontology["entities"] if item["type"] == "calls.Session"
    )
    assert session["fields"]["duration"]["type"] == "number"
    assert before["ontology_fingerprint"] != first["ontology_fingerprint"]

    query = application.execute_query(
        {
            "query_ir_version": "1",
            "match": {"nodes": [{"type": "calls.Session", "as": "session"}]},
            "where": [
                {
                    "left": {"field": "session.id"},
                    "op": "eq",
                    "right": {"value": "s2"},
                }
            ],
            "return": [
                {"field": "session.status"},
                {"field": "session.duration"},
            ],
        }
    )
    binding = query["rows"][0]["bindings"]["session"]
    assert query["rows"][0]["projections"][0]["node_id"] == binding
    projections = query["rows"][0]["projections"]
    assert projections[0]["value"] is None
    assert projections[1]["value"] == 42


def test_import_rejects_duplicates_types_and_credentials_without_writes(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, database, evidence_root = m5
    duplicate = _write(tmp_path / "duplicate.jsonl", [{"id": "s1"}, {"id": "s1"}])
    with pytest.raises(ImportValidationError, match="duplicate import key"):
        _import(application, duplicate, "calls.Session")
    mixed = _write(
        tmp_path / "mixed.jsonl",
        [{"id": "s1", "value": 1}, {"id": "s2", "value": "one"}],
    )
    with pytest.raises(ImportValidationError, match="mixes"):
        _import(application, mixed, "calls.Session")
    credential = _write(
        tmp_path / "credential.jsonl", [{"id": "s1", "password": "secret"}]
    )
    with pytest.raises(ProhibitedContentError):
        _import(application, credential, "calls.Session")
    assert application.ontology()["document"]["statistics"]["nodes"] == 0
    assert list((evidence_root / "objects" / "sha256").glob("*/*")) == []


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"value": 1}, "missing or null"),
        ({"id": None}, "missing or null"),
        ({"id": [1]}, "must be scalar"),
    ],
)
def test_import_key_validation_reports_line(
    m5: tuple[Any, ...], tmp_path: Path, record: dict[str, Any], message: str
) -> None:
    application, _, _ = m5
    source = _write(tmp_path / "invalid-key.jsonl", [record])
    with pytest.raises(ImportValidationError, match=f"line 1:.*{message}"):
        _import(application, source, "calls.Session")


@pytest.mark.parametrize(
    "raw",
    [
        '{"id":"first","id":"second"}\n',
        '{"id":"s1","score":NaN}\n',
        '{"id":"s1","score":Infinity}\n',
    ],
)
def test_jsonl_rejects_duplicate_keys_and_non_finite_numbers(
    m5: tuple[Any, ...], tmp_path: Path, raw: str
) -> None:
    application, _, _ = m5
    source = tmp_path / "strict.jsonl"
    source.write_text(raw, encoding="utf-8")
    with pytest.raises(ImportValidationError, match="line 1: invalid JSON"):
        _import(application, source, "calls.Session")


def test_ambiguous_import_rolls_back_and_reports_orphan_evidence(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, database, evidence_root = m5
    original = _write(
        tmp_path / "original.jsonl",
        [{"id": "s1", "code": "same"}, {"id": "s2", "code": "same"}],
    )
    _import(application, original, "calls.Session")
    conflicting = _write(tmp_path / "conflicting.jsonl", [{"code": "same", "value": 1}])
    digest = sha256(conflicting.read_bytes()).hexdigest()
    before = {
        table: len(application.memory_store.snapshot_records()[table])
        for table in ("node", "node_attribute")
    }
    before["observed_field"] = len(
        application.ontology()["document"]["entities"][0]["fields"]
    )
    with pytest.raises(ImportValidationError, match="ambiguous import key"):
        _import(
            application,
            conflicting,
            "calls.Session",
            [{"field": "code", "type": "string"}],
        )
    after = {
        table: len(application.memory_store.snapshot_records()[table])
        for table in ("node", "node_attribute")
    }
    after["observed_field"] = len(
        application.ontology()["document"]["entities"][0]["fields"]
    )
    assert after == before
    object_path = evidence_root / "objects" / "sha256" / digest[:2] / digest
    assert object_path.is_file()
    assert digest in {
        item["digest"] for item in application.evidence_audit()["orphans"]
    }

    application.evidence_store.put(
        conflicting,
        EvidenceObjectRecord(
            id="preexisting",
            digest=digest,
            byte_size=conflicting.stat().st_size,
            media_type="application/x-ndjson",
            privacy_class="public",
            recorded_at="2000-01-01T00:00:00Z",
        ),
    )
    with pytest.raises(ImportValidationError, match="ambiguous import key"):
        _import(
            application,
            conflicting,
            "calls.Session",
            [{"field": "code", "type": "string"}],
        )
    assert object_path.is_file()


def test_declaration_tightens_privacy_and_rejects_loosening(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, database, _ = m5
    source = _write(tmp_path / "sessions.jsonl", [{"id": "s1", "status": "ok"}])
    _import(application, source, "calls.Session")
    application.declare_entity(
        "calls.Session",
        privacy="private",
        contract_fingerprint=application.schema.fingerprint,
    )
    node_id = application.execute_query(
        {
            "query_ir_version": "1",
            "match": {"nodes": [{"type": "calls.Session", "as": "session"}]},
            "return": [{"field": "session.id"}],
        }
    )["rows"][0]["bindings"]["session"]
    assert application.memory_store.get_node(node_id)["privacy_class"] == "private"
    with pytest.raises(OntologyConflictError, match="cannot be loosened"):
        application.declare_entity(
            "calls.Session",
            privacy="public",
            contract_fingerprint=application.schema.fingerprint,
        )


def test_reused_evidence_privacy_only_tightens(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    source = _write(tmp_path / "shared.jsonl", [{"id": "s1", "status": "ok"}])
    public_import = _import(application, source, "public.Session")
    application.declare_entity(
        "private.Session",
        privacy="private",
        contract_fingerprint=application.schema.fingerprint,
    )
    _import(application, source, "private.Session")
    _import(application, source, "another.Session")

    catalog, truncated = application.memory_store.evidence_catalog(
        1, public_import["evidence_digest"]
    )
    assert truncated is False
    assert catalog[0]["effective_privacy"] == "private"
    assert catalog[0]["object"]["privacy_class"] == "private"
    assert {item["privacy_class"] for item in catalog[0]["fragments"]} == {"private"}
    assert {item["privacy_class"] for item in catalog[0]["acquisitions"]} == {
        "public",
        "private",
    }
    assert (
        application.evidence_status(public_import["evidence_digest"])[
            "effective_privacy"
        ]
        == "private"
    )


def test_import_replay_repairs_missing_evidence_location(
    m5: tuple[Any, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, _, _ = m5
    source = _write(tmp_path / "repair.jsonl", [{"id": "s1"}])
    original = application.memory_store.record_evidence_check
    failed = False

    def fail_once(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("forced location-recording failure")
        return cast(dict[str, Any], original(*args, **kwargs))

    monkeypatch.setattr(application.memory_store, "record_evidence_check", fail_once)
    with pytest.raises(RuntimeError, match="forced location-recording failure"):
        _import(application, source, "calls.Session")

    replay = _import(application, source, "calls.Session")
    assert replay["replayed"] is True
    catalog, _ = application.memory_store.evidence_catalog(1, replay["evidence_digest"])
    assert catalog[0]["locations"][0]["availability"] == "present"


def test_retention_release_plan_and_retire_are_explicit_and_audited(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    imported = _import(
        application,
        _write(tmp_path / "retained.jsonl", [{"id": "s1"}]),
        "calls.Session",
    )
    digest = imported["evidence_digest"]
    before = application.retention_plan(
        tmp_path / "before-release.json",
        digests=[digest],
        created_at="2026-01-01T00:00:00Z",
    )
    assert before["objects"] == []
    with pytest.raises(ValueError, match="confirmation"):
        application.retention_release(
            digest,
            confirmation="wrong",
            reason="reviewed",
            released_at="2026-01-02T00:00:00Z",
        )

    released = application.retention_release(
        digest,
        confirmation=digest,
        reason="reviewed for retirement",
        released_at="2026-01-02T00:00:00Z",
    )
    assert released["retention_state"] == "expired"
    assert released["acquisition_ids"]
    acquisition = next(
        item
        for item in application.memory_store.snapshot_records()["evidence_acquisition"]
        if item["evidence_object_id"]
        == application.memory_store.evidence_catalog(1, digest)[0][0]["object"]["id"]
    )
    assert acquisition["retention_required"] == 0
    assert acquisition["released_at"] == "2026-01-02T00:00:00Z"
    assert acquisition["release_reason"] == "reviewed for retirement"

    plan_path = tmp_path / "after-release.json"
    plan = application.retention_plan(
        plan_path,
        digests=[digest],
        created_at="2026-01-03T00:00:00Z",
    )
    assert [item["digest"] for item in plan["objects"]] == [digest]
    retired = application.retention_retire(
        plan_path,
        confirmation=plan["plan_id"],
        retired_at="2026-01-04T00:00:00Z",
    )
    assert retired["retired_digests"] == [digest]
    assert application.evidence_status(digest)["retired"] is True
    assert application.evidence_status(digest)["availability"] == "missing"
    with pytest.raises(RetentionBlockedError, match="already retired"):
        application.retention_release(
            digest,
            confirmation=digest,
            reason="too late",
            released_at="2026-01-05T00:00:00Z",
        )


def test_retention_release_is_idempotent_and_preserves_retain_until(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    imported = _import(
        application,
        _write(tmp_path / "retained-until.jsonl", [{"id": "s1"}]),
        "calls.Session",
    )
    digest = imported["evidence_digest"]
    connection = application.memory_store._connect()
    with connection:
        connection.execute(
            "UPDATE evidence_acquisition SET retention_required = 0, retain_until = ?",
            ("2026-01-02T00:00:00Z",),
        )

    with pytest.raises(ValueError, match="must not be empty"):
        application.retention_release(
            digest,
            confirmation=digest,
            reason="   ",
            released_at="2026-01-01T00:00:00Z",
        )
    first = application.retention_release(
        digest,
        confirmation=digest,
        reason="first review",
        released_at="2026-01-01T00:00:00Z",
    )
    assert first["retention_state"] == "active"
    assert first["acquisition_ids"]
    report = application.retention_report(as_of="2026-01-02T01:00:00+02:00")
    assert report["as_of"] == "2026-01-01T23:00:00Z"
    assert report["objects"][0]["retention_state"] == "active"
    assert report["objects"][0]["releases"] == first["releases"]

    second = application.retention_release(
        digest,
        confirmation=digest,
        reason="must not replace the first audit",
        released_at="2026-01-03T00:00:00Z",
    )
    assert second["acquisition_ids"] == []
    assert second["released_at"] == "2026-01-01T00:00:00Z"
    assert second["reason"] == "first review"
    assert second["releases"] == first["releases"]
    persisted = application.memory_store.snapshot_records()["evidence_acquisition"][0]
    assert persisted["retain_until"] == "2026-01-02T00:00:00Z"


def test_retention_release_reports_the_new_audit_for_a_reacquired_object(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    source = _write(tmp_path / "reacquired.jsonl", [{"id": "s1"}])
    first_import = _import(application, source, "calls.FirstSession")
    digest = first_import["evidence_digest"]
    application.retention_release(
        digest,
        confirmation=digest,
        reason="first review",
        released_at="2026-01-01T00:00:00Z",
    )
    second_import = _import(application, source, "calls.SecondSession")
    assert second_import["evidence_digest"] == digest

    second_release = application.retention_release(
        digest,
        confirmation=digest,
        reason="second review",
        released_at="2026-01-02T00:00:00Z",
    )

    assert second_release["acquisition_ids"]
    assert second_release["released_at"] == "2026-01-02T00:00:00Z"
    assert second_release["reason"] == "second review"
    assert len(second_release["releases"]) == 2


def test_failed_retirement_does_not_claim_the_store_copy_is_missing(
    m5: tuple[Any, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application, _, _ = m5
    imported = _import(
        application,
        _write(tmp_path / "retire-failure.jsonl", [{"id": "s1"}]),
        "calls.Session",
    )
    digest = imported["evidence_digest"]
    application.retention_release(
        digest,
        confirmation=digest,
        reason="reviewed",
        released_at="2026-01-01T00:00:00Z",
    )
    plan_path = tmp_path / "retire-failure-plan.json"
    plan = application.retention_plan(
        plan_path,
        digests=[digest],
        created_at="2026-01-02T00:00:00Z",
    )
    original_retire = application.evidence_store.retire

    def fail_retire(_: str) -> bool:
        raise OSError("forced removal failure")

    monkeypatch.setattr(application.evidence_store, "retire", fail_retire)
    failed = application.retention_retire(
        plan_path,
        confirmation=plan["plan_id"],
        retired_at="2026-01-03T00:00:00Z",
    )
    assert failed["outcomes"][0]["store_copy"] == "removal_failed"
    assert application.evidence_status(digest)["retired"] is True
    assert application.evidence_status(digest)["availability"] == "present"

    monkeypatch.setattr(application.evidence_store, "retire", original_retire)
    retried = application.retention_retire(
        plan_path,
        confirmation=plan["plan_id"],
        retired_at="2026-01-04T00:00:00Z",
    )
    assert retried["outcomes"][0]["store_copy"] == "removed"
    assert application.evidence_status(digest)["availability"] == "missing"


def test_integrity_detects_search_index_drift(m5: tuple[Any, ...]) -> None:
    application, _, _ = m5
    connection = application.memory_store._connect()
    with connection:
        connection.execute(
            "INSERT INTO search_document_fts(document_id, content) VALUES (?, ?)",
            ("orphan", "orphan content"),
        )

    integrity = application.memory_store.integrity()

    assert integrity["ok"] is False
    assert integrity["checks"]["search_index"]["extra_rows"] == 1
    assert set(integrity["checks"]["foreign_keys"]) == {
        "errors",
        "ok",
        "orphan_counts",
    }


def test_declaration_conflicts_leave_current_ontology_unchanged(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, evidence_root = m5
    source = _write(
        tmp_path / "sessions.jsonl", [{"id": "s1", "status": "ok", "note": None}]
    )
    _import(application, source, "calls.Session")
    before = application.ontology()["ontology_fingerprint"]
    objects_before = set((evidence_root / "objects" / "sha256").glob("*/*"))
    with pytest.raises(OntologyConflictError, match="already has type"):
        application.declare_entity(
            "calls.Session",
            fields={"status": {"type": "number"}},
            contract_fingerprint=application.schema.fingerprint,
        )
    with pytest.raises(OntologyConflictError, match="current null"):
        application.declare_entity(
            "calls.Session",
            fields={"note": {"nullable": False}},
            contract_fingerprint=application.schema.fingerprint,
        )
    assert application.ontology()["ontology_fingerprint"] == before
    objects_after = set((evidence_root / "objects" / "sha256").glob("*/*"))
    assert objects_before < objects_after
    orphan_digests = {
        item["digest"] for item in application.evidence_audit()["orphans"]
    }
    assert {path.name for path in objects_after - objects_before} == orphan_digests


def test_redeclaration_resets_omitted_field_constraints_and_search(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    application.declare_entity(
        "calls.Session",
        fields={
            "id": {"type": "string", "required": True, "nullable": False},
            "status": {
                "type": "string",
                "required": True,
                "nullable": False,
                "searchable": True,
            },
        },
        contract_fingerprint=application.schema.fingerprint,
    )
    _import(
        application,
        _write(tmp_path / "searchable.jsonl", [{"id": "s1", "status": "failed"}]),
        "calls.Session",
    )
    assert application.search_text("failed", 10)["results"]

    application.declare_entity(
        "calls.Session",
        fields={"id": {"type": "string", "required": True, "nullable": False}},
        contract_fingerprint=application.schema.fingerprint,
    )

    entity = application.ontology()["document"]["entities"][0]
    assert entity["fields"]["status"] == {
        "declared": False,
        "description": None,
        "nullable": True,
        "privacy": "public",
        "required": False,
        "searchable": False,
        "type": "string",
    }
    assert application.search_text("failed", 10)["coverage"] == {
        "complete": True,
        "eligible_count": 0,
        "indexed_count": 0,
    }
    records = application.memory_store.snapshot_records()
    status_attribute = next(
        item for item in records["node_attribute"] if item["attribute_name"] == "status"
    )
    assert status_attribute["searchable"] == 0
    status_document = next(
        item
        for item in records["search_document"]
        if item["target_id"] == status_attribute["id"]
    )
    assert status_document["lifecycle"] == "stale"

    application.declare_entity(
        "calls.Session",
        fields={
            "id": {"type": "string", "required": True, "nullable": False},
            "status": {"type": "string", "searchable": True},
        },
        contract_fingerprint=application.schema.fingerprint,
    )
    restored = application.search_text("failed", 10)
    assert restored["results"][0]["value"] == "failed"
    assert restored["coverage"] == {
        "complete": True,
        "eligible_count": 1,
        "indexed_count": 1,
    }


def test_withdrawn_unobserved_declaration_does_not_pin_type(
    m5: tuple[Any, ...],
) -> None:
    application, _, _ = m5
    application.declare_entity(
        "calls.Session",
        fields={"future": {"type": "number", "privacy": "private"}},
        contract_fingerprint=application.schema.fingerprint,
    )
    application.declare_entity(
        "calls.Session",
        contract_fingerprint=application.schema.fingerprint,
    )
    withdrawn = application.ontology()["document"]["entities"][0]["fields"]["future"]
    assert withdrawn["type"] == "unresolved"
    assert withdrawn["privacy"] == "private"

    application.declare_entity(
        "calls.Session",
        fields={"future": {"type": "string", "privacy": "private"}},
        contract_fingerprint=application.schema.fingerprint,
    )
    restored = application.ontology()["document"]["entities"][0]["fields"]["future"]
    assert restored["type"] == "string"
    assert restored["declared"] is True


def test_bidirectional_traversal_does_not_lose_visited_edges_to_limit(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    _import(
        application,
        _write(
            tmp_path / "nodes.jsonl",
            [
                {"id": "A", "parent": None},
                {"id": "B", "parent": "A"},
                {"id": "C", "parent": "B"},
                {"id": "D", "parent": "C"},
            ],
        ),
        "graph.Node",
    )
    application.materialize_join(
        name="parent",
        relation="parent",
        from_={"type": "graph.Node", "fields": ["parent"]},
        to={"type": "graph.Node", "fields": ["id"]},
        contract_fingerprint=application.schema.fingerprint,
    )
    reordered_edges = application.execute_query(
        {
            "query_ir_version": "1",
            "match": {
                "nodes": [
                    {"type": "graph.Node", "as": "a"},
                    {"type": "graph.Node", "as": "b"},
                    {"type": "graph.Node", "as": "c"},
                ],
                "edges": [
                    {"type": "parent", "from": "c", "to": "b"},
                    {"type": "parent", "from": "b", "to": "a"},
                ],
            },
            "where": [
                {
                    "left": {"field": "a.id"},
                    "op": "eq",
                    "right": {"value": "A"},
                }
            ],
            "return": [{"count": True}],
        }
    )
    assert reordered_edges["count"] == 1
    start = application.execute_query(
        {
            "query_ir_version": "1",
            "match": {"nodes": [{"type": "graph.Node", "as": "node"}]},
            "where": [
                {
                    "left": {"field": "node.id"},
                    "op": "eq",
                    "right": {"value": "A"},
                }
            ],
            "return": [{"field": "node.id"}],
        }
    )["rows"][0]["bindings"]["node"]

    traversal = application.traverse_relations(
        start, direction="both", max_depth=3, limit=3
    )
    assert len(traversal["edges"]) == 3
    assert len({item["relation_id"] for item in traversal["edges"]}) == 3
    assert {item["depth"] for item in traversal["edges"]} == {1, 2, 3}
    assert traversal["truncated"] is False

    exact_limit = application.traverse_relations(
        start, direction="both", max_depth=4, limit=3
    )
    assert len(exact_limit["edges"]) == 3
    assert exact_limit["truncated"] is False

    _import(
        application,
        _write(tmp_path / "more-nodes.jsonl", [{"id": "E", "parent": "D"}]),
        "graph.Node",
    )
    application.materialize_join(
        name="parent",
        relation="parent",
        from_={"type": "graph.Node", "fields": ["parent"]},
        to={"type": "graph.Node", "fields": ["id"]},
        contract_fingerprint=application.schema.fingerprint,
        idempotency_key="parent-with-e",
    )
    depth_capped = application.traverse_relations(
        start, direction="both", max_depth=3, limit=10
    )
    assert len(depth_capped["edges"]) == 3
    assert depth_capped["truncated"] is True


def test_join_query_rerun_correction_and_cascade(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, database, _ = m5
    sessions = _write(
        tmp_path / "sessions.jsonl",
        [{"id": "s1", "status": "ok"}, {"id": "s2", "status": "failed"}],
    )
    messages = _write(
        tmp_path / "messages.jsonl",
        [
            {"id": "m1", "session_id": "s1", "message": "hello"},
            {"id": "m2", "session_id": "s2", "message": "bye"},
        ],
    )
    _import(application, sessions, "calls.Session")
    _import(application, messages, "calls.SessionMessage")
    arguments = {
        "name": "message_to_session",
        "relation": "session",
        "from_": {"type": "calls.SessionMessage", "fields": ["session_id"]},
        "to": {"type": "calls.Session", "fields": ["id"]},
        "contract_fingerprint": application.schema.fingerprint,
    }
    first = application.materialize_join(**arguments, idempotency_key="join-1")
    second = application.materialize_join(**arguments, idempotency_key="join-2")
    assert first["created_relations"] == 2
    assert second["previously_materialized_active"] == 2
    relation_ontology = application.ontology()["document"]["relations"][0]
    assert relation_ontology["statistics"]["active_edges"] == 2
    assert relation_ontology["provenance"]["fragment_id"] is not None
    assert second["ontology_fingerprint"] == first["ontology_fingerprint"]
    with pytest.raises(JoinConflictError, match="another definition"):
        application.materialize_join(
            **{**arguments, "relation": "different"}, idempotency_key="join-conflict"
        )

    query = application.execute_query(
        {
            "query_ir_version": "1",
            "match": {
                "nodes": [
                    {"type": "calls.Session", "as": "session"},
                    {"type": "calls.SessionMessage", "as": "message"},
                ],
                "edges": [{"type": "session", "from": "message", "to": "session"}],
            },
            "where": [
                {
                    "left": {"field": "session.status"},
                    "op": "eq",
                    "right": {"value": "failed"},
                }
            ],
            "return": [{"field": "message.message"}],
        }
    )
    assert query["rows"][0]["projections"][0]["value"] == "bye"
    keyed_count = application.execute_query(
        {
            "query_ir_version": "1",
            "match": {
                "nodes": [
                    {"type": "calls.Session", "as": "session"},
                    {"type": "calls.SessionMessage", "as": "message"},
                ],
                "edges": [
                    {
                        "type": "session",
                        "from": "message",
                        "to": "session",
                        "logical_key": "message_to_session",
                    }
                ],
            },
            "return": [{"count": True}],
        }
    )
    assert keyed_count["count"] == 2
    with pytest.raises(QueryValidationError, match="conflicts"):
        application.execute_query(
            {
                "query_ir_version": "1",
                "match": {"nodes": [{"type": "calls.Session", "as": "s"}]},
                "where": [
                    {
                        "left": {"field": "s.id"},
                        "op": "eq",
                        "right": {"value": 1},
                    }
                ],
                "return": [{"field": "s.id"}],
            }
        )

    source_node_id = query["rows"][0]["bindings"]["message"]
    traversal = application.traverse_relations(source_node_id, direction="outbound")
    relation_id = traversal["edges"][0]["relation_id"]
    assert traversal["edges"][0]["relation_type"] == "session"
    explanation = application.explain_relation(relation_id)
    assert explanation["relation"]["relation_type"] == "session"
    assert explanation["evidence"]["status"]["verification"] == "verified"
    deactivated = application.deactivate_relation(relation_id)
    assert deactivated["relation_type"] == "session"
    assert deactivated["active"] is False
    assert (
        application.deactivate_relation(relation_id)["updated_at"]
        == deactivated["updated_at"]
    )
    assert (
        application.ontology()["ontology_fingerprint"] == first["ontology_fingerprint"]
    )
    third = application.materialize_join(**arguments, idempotency_key="join-3")
    assert third["previously_materialized_inactive"] == 1
    deleted = application.delete_node(source_node_id)
    assert deleted["attributes"] == 3
    assert deleted["relations"] == 1


def test_ambiguous_join_rolls_back_declaration(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    sessions = _write(
        tmp_path / "sessions.jsonl",
        [{"id": "s1", "code": "same"}, {"id": "s2", "code": "same"}],
    )
    messages = _write(
        tmp_path / "messages.jsonl",
        [{"id": "m1", "session_code": "same"}],
    )
    _import(application, sessions, "calls.Session")
    _import(application, messages, "calls.SessionMessage")
    with pytest.raises(AmbiguousTargetError):
        application.materialize_join(
            name="ambiguous",
            relation="session",
            from_={"type": "calls.SessionMessage", "fields": ["session_code"]},
            to={"type": "calls.Session", "fields": ["code"]},
            contract_fingerprint=application.schema.fingerprint,
        )
    assert application.ontology()["document"]["relations"] == []


def test_join_expands_source_arrays_with_cartesian_product(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    sources = _write(
        tmp_path / "sources.jsonl",
        [
            {"id": "src1", "codes": ["a", "b", "b"], "regions": ["1", "2"]},
            {"id": "src2", "codes": [None], "regions": ["1"]},
            {"id": "src3", "codes": ["q"], "regions": ["9"]},
        ],
    )
    targets = _write(
        tmp_path / "targets.jsonl",
        [
            {"id": "t1", "code": "b", "region": "1"},
            {"id": "t2", "code": "a", "region": "2"},
            {"id": "t3", "code": "a", "region": "1"},
            {"id": "t4", "code": "b", "region": "2"},
        ],
    )
    codes = _write(
        tmp_path / "codes.jsonl",
        [{"id": "c1", "code": "a"}, {"id": "c2", "code": "b"}],
    )
    array_targets = _write(
        tmp_path / "array-targets.jsonl",
        [{"id": "at1", "codes": ["a", "b"]}],
    )
    _import(application, sources, "example.Source")
    _import(application, targets, "example.Target")
    _import(application, codes, "example.Code")
    _import(application, array_targets, "example.ArrayTarget")

    array_join = {
        "name": "source-target-arrays",
        "relation": "matches",
        "from_": {
            "type": "example.Source",
            "fields": ["codes", "regions"],
        },
        "to": {
            "type": "example.Target",
            "fields": ["code", "region"],
        },
        "contract_fingerprint": application.schema.fingerprint,
    }
    first = application.materialize_join(**array_join, idempotency_key="arrays-1")
    second = application.materialize_join(**array_join, idempotency_key="arrays-2")

    assert first["created_relations"] == 4
    assert first["skipped_null_or_missing"] == 1
    assert first["skipped_unmatched"] == 1
    assert second["created_relations"] == 0
    assert second["previously_materialized_active"] == 4

    source_to_scalar = application.materialize_join(
        name="source-code",
        relation="contains_code",
        from_={"type": "example.Source", "fields": ["codes"]},
        to={"type": "example.Code", "fields": ["code"]},
        contract_fingerprint=application.schema.fingerprint,
    )
    assert source_to_scalar["created_relations"] == 2
    assert source_to_scalar["skipped_null_or_missing"] == 1
    assert source_to_scalar["skipped_unmatched"] == 1

    with pytest.raises(JoinConflictError, match="target fields must be scalar"):
        application.materialize_join(
            name="code-array-target",
            relation="in_target",
            from_={"type": "example.Code", "fields": ["code"]},
            to={"type": "example.ArrayTarget", "fields": ["codes"]},
            contract_fingerprint=application.schema.fingerprint,
        )


def test_join_rejects_non_scalar_array_elements(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    sources = _write(
        tmp_path / "sources.jsonl",
        [{"id": "src1", "codes": ["a", {"code": "b"}]}],
    )
    targets = _write(
        tmp_path / "targets.jsonl",
        [{"id": "t1", "code": "a"}],
    )
    _import(application, sources, "example.Source")
    _import(application, targets, "example.Target")

    with pytest.raises(JoinConflictError, match="require scalar elements"):
        application.materialize_join(
            name="invalid-array-elements",
            relation="matches",
            from_={"type": "example.Source", "fields": ["codes"]},
            to={"type": "example.Target", "fields": ["code"]},
            contract_fingerprint=application.schema.fingerprint,
        )
    assert application.ontology()["document"]["relations"] == []


def test_analytical_value_uses_attribute_shape_and_direct_provenance(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, database, _ = m5
    source = _write(tmp_path / "sessions.jsonl", [{"id": "s1", "status": "ok"}])
    _import(application, source, "calls.Session")
    node_id = application.execute_query(
        {
            "query_ir_version": "1",
            "match": {"nodes": [{"type": "calls.Session", "as": "session"}]},
            "return": [{"field": "session.id"}],
        }
    )["rows"][0]["bindings"]["session"]
    first = application.write_analytical_attribute(
        node_id,
        "classification",
        {"label": "excellent", "score": 0.9},
        method="session-classifier-v1",
        contract_fingerprint=application.schema.fingerprint,
    )
    replay = application.write_analytical_attribute(
        node_id,
        "classification",
        {"label": "excellent", "score": 0.9},
        method="session-classifier-v1",
        contract_fingerprint=application.schema.fingerprint,
    )
    assert replay["replayed"] is True
    explanation = application.explain(first["attribute_id"])
    assert explanation["attribute"]["value"]["label"] == "excellent"
    assert explanation["attribute"]["batch_id"] is None
    assert explanation["attribute"]["run_id"] == first["run_id"]
    assert explanation["evidence"]["status"]["verification"] == "verified"
    row = next(
        row
        for row in application.memory_store.snapshot_records()["analytical_run"]
        if row["id"] == first["run_id"]
    )
    assert (row["batch_id"], row["method"]) == (None, "session-classifier-v1")


def test_analytical_metric_write_query_replay_and_explain(m5: tuple[Any, ...]) -> None:
    application, _, _ = m5
    arguments = {
        "definition_version": "completion-rate-v1",
        "value": 0.75,
        "dimensions": {"channel": "voice"},
        "method": "aggregate-v1",
        "method_version": "1",
        "contract_fingerprint": application.schema.fingerprint,
        "coverage": {"included": 3, "total": 4},
        "unit": "ratio",
        "numerator": 3.0,
        "denominator": 4.0,
    }
    first = application.write_analytical_metric(**arguments)
    replay = application.write_analytical_metric(**arguments)
    assert replay["replayed"] is True
    current = application.current_metric("completion-rate-v1", {"channel": "voice"})
    assert current["metric"]["value"] == 0.75
    assert current["metric"]["run_id"] == first["run_id"]
    explanation = application.explain_metric(first["metric_id"])
    assert explanation["metric"]["numerator"] == 3.0
    assert explanation["run"]["batch_id"] is None
    assert explanation["evidence"]["status"]["verification"] == "verified"


def test_namespace_filter_treats_underscore_literally(
    m5: tuple[Any, ...], tmp_path: Path
) -> None:
    application, _, _ = m5
    _import(
        application,
        _write(tmp_path / "one.jsonl", [{"id": "1"}]),
        "call_center.Session",
    )
    _import(
        application,
        _write(tmp_path / "two.jsonl", [{"id": "2"}]),
        "callXcenter.Session",
    )
    entities = application.ontology("call_center")["document"]["entities"]
    assert [entity["type"] for entity in entities] == ["call_center.Session"]


def test_query_count_offset_and_truncation(m5: tuple[Any, ...], tmp_path: Path) -> None:
    application, _, _ = m5
    source = _write(
        tmp_path / "sessions.jsonl",
        [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}],
    )
    _import(application, source, "calls.Session")
    match = {"nodes": [{"type": "calls.Session", "as": "s"}]}
    counted = application.execute_query(
        {
            "query_ir_version": "1",
            "match": match,
            "return": [{"count": True}],
        }
    )
    assert counted["count"] == 3
    page = application.execute_query(
        {
            "query_ir_version": "1",
            "match": match,
            "return": [{"field": "s.id"}],
            "order_by": [{"field": "s.id", "direction": "asc"}],
            "limit": 1,
            "offset": 1,
        }
    )
    assert page["rows"][0]["projections"][0]["value"] == "s2"
    assert page["truncated"] is True


def test_text_semantic_snapshot_and_public_export(tmp_path: Path) -> None:
    schema = load_schema(default_schema_path())
    database = tmp_path / "memory.db"
    evidence_root = tmp_path / "evidence"
    application = MemoryApplication(
        SqliteMemoryStore(database),
        FileEvidenceStore(evidence_root),
        schema,
        FixtureEmbeddingProvider(),
    )
    application.initialize()
    application.declare_namespace(
        "calls",
        "Call records.",
        contract_fingerprint=schema.fingerprint,
    )
    application.declare_entity(
        "calls.Session",
        description="One call session.",
        fields={
            "status": {"type": "string", "searchable": True},
            "note": {
                "type": "string",
                "searchable": True,
                "privacy": "private",
            },
        },
        contract_fingerprint=schema.fingerprint,
    )
    source = _write(
        tmp_path / "sessions.jsonl",
        [
            {"id": "s1", "status": "failed payment", "note": "private note"},
            {"id": "s2", "status": "completed", "note": "hidden"},
        ],
    )
    imported = _import(application, source, "calls.Session")
    assert (
        application.evidence_status(imported["evidence_digest"])["effective_privacy"]
        == "private"
    )
    text = application.search_text("failed", 10)
    assert text["results"][0]["source_id"] == imported["source_id"]
    assert text["results"][0]["fragment_id"] == imported["fragment_id"]

    profile = application.embedding_profile_create("status")["profile"]
    rebuilt = application.embedding_rebuild(profile["id"])
    assert rebuilt["coverage"] == {
        "eligible_count": 2,
        "indexed_count": 2,
        "complete": True,
    }
    semantic = application.search_semantic(profile["id"], "failed", limit=1)
    assert semantic["results"][0]["value"] == "failed payment"
    assert semantic["results"][0]["source_id"] == imported["source_id"]

    exported = tmp_path / "public.json"
    application.sanitized_export(exported)
    public = json.loads(exported.read_text(encoding="utf-8"))
    assert {item["attribute_name"] for item in public["attributes"]} == {
        "id",
        "status",
    }

    snapshot = tmp_path / "snapshot.tar.gz"
    source_ontology = application.ontology()
    manifest = application.snapshot_create(snapshot)
    restored = MemoryApplication(
        SqliteMemoryStore(tmp_path / "restored.db"),
        FileEvidenceStore(tmp_path / "restored-evidence"),
        schema,
    )
    result = restored.snapshot_import(snapshot)
    assert result["snapshot_id"] == manifest["snapshot_id"]
    assert restored.ontology() == source_ontology
    assert restored.ontology()["document"]["statistics"]["nodes"] == 2

    orphan_data = b"orphan"
    orphan_digest = sha256(orphan_data).hexdigest()
    orphan_path = (
        evidence_root / "objects" / "sha256" / orphan_digest[:2] / orphan_digest
    )
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_bytes(orphan_data)
    audit = application.evidence_audit()
    assert [item["digest"] for item in audit["orphans"]] == [orphan_digest]


def test_m5_cli_import_ontology_and_query(tmp_path: Path, capsys: Any) -> None:
    database = tmp_path / "memory.db"
    evidence = tmp_path / "evidence"
    source = _write(tmp_path / "sessions.jsonl", [{"id": "s1", "status": "ok"}])
    query = tmp_path / "query.json"
    query.write_text(
        json.dumps(
            {
                "query_ir_version": "1",
                "match": {"nodes": [{"type": "calls.Session", "as": "s"}]},
                "return": [{"field": "s.status"}],
            }
        ),
        encoding="utf-8",
    )
    shared = ["--database", str(database), "--evidence-root", str(evidence)]
    assert main([*shared, "init"]) == 0
    capsys.readouterr()
    fingerprint = load_schema(default_schema_path()).fingerprint
    assert (
        main(
            [
                *shared,
                "ontology",
                "declare-namespace",
                "calls",
                "--description",
                "Call records.",
                "--contract-fingerprint",
                fingerprint,
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                *shared,
                "jsonl",
                "import",
                str(source),
                "--entity-type",
                "calls.Session",
                "--key",
                '[{"field":"id","type":"string"}]',
                "--contract-fingerprint",
                fingerprint,
            ]
        )
        == 0
    )
    imported = json.loads(capsys.readouterr().out)
    digest = imported["evidence_digest"]
    assert (
        main(
            [
                *shared,
                "retention",
                "release",
                digest,
                "--confirm",
                digest,
                "--reason",
                "CLI review",
            ]
        )
        == 0
    )
    released = json.loads(capsys.readouterr().out)
    assert released["acquisition_ids"]
    assert main([*shared, "ontology", "describe"]) == 0
    ontology = json.loads(capsys.readouterr().out)
    assert ontology["document"]["namespaces"][0]["description"] == "Call records."
    assert ontology["document"]["entities"][0]["type"] == "calls.Session"
    assert main([*shared, "query", "execute", "--document", str(query)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["rows"][0]["projections"][0]["value"] == "ok"


@pytest.mark.anyio
async def test_real_m5_flow_through_mcp(m5: tuple[Any, ...], tmp_path: Path) -> None:
    application, database, evidence_root = m5
    sessions = _write(
        tmp_path / "sessions.jsonl", [{"id": "s1", "status": "ok", "note": None}]
    )
    messages = _write(
        tmp_path / "messages.jsonl",
        [{"id": "m1", "session_id": "s1", "message": "hello"}],
    )
    environment: dict[str, str] = {
        **os.environ,
        "ANALYTICAL_MEMORY_EVIDENCE_ROOT": str(evidence_root),
        "ANALYTICAL_MEMORY_SCHEMA": str(default_schema_path()),
    }
    if database is None:
        store = application.memory_store
        environment.update(
            {
                "ANALYTICAL_MEMORY_BACKEND": "postgresql",
                "ANALYTICAL_MEMORY_POSTGRES_URL": str(store.dsn),
                "ANALYTICAL_MEMORY_POSTGRES_SCHEMA": str(store.schema),
            }
        )
    else:
        environment["ANALYTICAL_MEMORY_BACKEND"] = "sqlite"
        environment["ANALYTICAL_MEMORY_DB"] = str(database)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "analytical_memory.mcp_server"],
        env=environment,
    )
    async with Client(parameters) as client:
        schema_resource = _resource_json(
            await client.read_resource("memory://schema/current")
        )
        fingerprint = str(schema_resource["schema_fingerprint"])
        query_contract = _resource_json(
            await client.read_resource("memory://schema/query-ir/current")
        )
        assert query_contract["input_schema"]["properties"]["match"]
        assert query_contract["semantics"]["bindings"]
        namespace_declaration = await client.call_tool(
            "memory_ontology_manage",
            {
                "action": "declare_namespace",
                "payload": {
                    "namespace": "calls",
                    "description": "Call records.",
                    "contract_fingerprint": fingerprint,
                },
            },
        )
        namespace_document = _tool_json(namespace_declaration)["document"]
        assert namespace_document["namespaces"][0]["description"] == "Call records."
        declaration = await client.call_tool(
            "memory_ontology_manage",
            {
                "action": "declare_entity",
                "payload": {
                    "entity_type": "calls.Session",
                    "contract_fingerprint": fingerprint,
                    "description": "One call session.",
                    "fields": {
                        "id": {
                            "description": "Session identifier.",
                            "type": "string",
                            "required": True,
                        },
                        "note": {"type": "string"},
                    },
                },
            },
        )
        assert declaration.is_error is False
        for path, entity_type in (
            (sessions, "calls.Session"),
            (messages, "calls.SessionMessage"),
        ):
            imported = await client.call_tool(
                "memory_ingest_manage",
                {
                    "action": "jsonl_import",
                    "payload": {
                        "source_path": str(path),
                        "entity_type": entity_type,
                        "key": [{"field": "id", "type": "string"}],
                        "contract_fingerprint": fingerprint,
                    },
                },
            )
            assert imported.is_error is False
        session_query = await client.call_tool(
            "memory_query_manage",
            {
                "action": "execute",
                "payload": {
                    "document": {
                        "query_ir_version": "1",
                        "match": {
                            "nodes": [{"type": "calls.Session", "as": "session"}]
                        },
                        "return": [{"field": "session.id"}],
                    }
                },
            },
        )
        session_node_id = _tool_json(session_query)["rows"][0]["bindings"]["session"]
        null_query = await client.call_tool(
            "memory_query_manage",
            {
                "action": "execute",
                "payload": {
                    "document": {
                        "query_ir_version": "1",
                        "match": {
                            "nodes": [{"type": "calls.Session", "as": "session"}]
                        },
                        "where": [
                            {
                                "left": {"field": "session.note"},
                                "op": "eq",
                                "right": {"value": None},
                            }
                        ],
                        "return": [{"field": "session.note"}],
                    }
                },
            },
        )
        assert len(_tool_json(null_query)["rows"]) == 1
        written = await client.call_tool(
            "memory_ingest_manage",
            {
                "action": "analytical_attribute",
                "payload": {
                    "node_id": session_node_id,
                    "attribute_name": "classification",
                    "value": "excellent",
                    "method": "mcp-test-v1",
                    "contract_fingerprint": fingerprint,
                },
            },
        )
        assert _tool_json(written)["attribute_id"]
        joined = await client.call_tool(
            "memory_relation_manage",
            {
                "action": "materialize",
                "payload": {
                    "name": "message_to_session",
                    "relation": "session",
                    "from": {
                        "type": "calls.SessionMessage",
                        "fields": ["session_id"],
                    },
                    "to": {"type": "calls.Session", "fields": ["id"]},
                    "contract_fingerprint": fingerprint,
                    "idempotency_key": "mcp-join",
                },
            },
        )
        assert _tool_json(joined)["created_relations"] == 1
        queried = await client.call_tool(
            "memory_query_manage",
            {
                "action": "execute",
                "payload": {
                    "document": {
                        "query_ir_version": "1",
                        "match": {
                            "nodes": [
                                {"type": "calls.Session", "as": "session"},
                                {"type": "calls.SessionMessage", "as": "message"},
                            ],
                            "edges": [
                                {
                                    "type": "session",
                                    "from": "message",
                                    "to": "session",
                                }
                            ],
                        },
                        "return": [{"field": "message.message"}],
                    }
                },
            },
        )
        query_result = _tool_json(queried)
        message_node_id = query_result["rows"][0]["bindings"]["message"]
        traversed = await client.call_tool(
            "memory_query_manage",
            {
                "action": "traverse",
                "payload": {
                    "start_node_id": message_node_id,
                    "direction": "outbound",
                },
            },
        )
        relation_id = _tool_json(traversed)["edges"][0]["relation_id"]
        corrected = await client.call_tool(
            "memory_relation_manage",
            {"action": "deactivate", "payload": {"relation_id": relation_id}},
        )
        assert _tool_json(corrected)["active"] is False
        metric = await client.call_tool(
            "memory_ingest_manage",
            {
                "action": "analytical_metric",
                "payload": {
                    "definition_version": "message-count-v1",
                    "value": 1,
                    "dimensions": {"entity": "SessionMessage"},
                    "method": "count-v1",
                    "method_version": "1",
                    "contract_fingerprint": fingerprint,
                },
            },
        )
        metric_id = _tool_json(metric)["metric_id"]
        explained_metric = await client.call_tool(
            "memory_explain_manage",
            {"action": "metric", "payload": {"metric_id": metric_id}},
        )
        deleted = await client.call_tool(
            "memory_node_delete", {"node_id": message_node_id}
        )
        assert _tool_json(deleted)["nodes"] == 1
        stale = await client.call_tool(
            "memory_ontology_manage",
            {
                "action": "declare_entity",
                "payload": {
                    "entity_type": "calls.Other",
                    "contract_fingerprint": "stale",
                },
            },
        )
        assert stale.is_error is True
        assert isinstance(stale.content[0], TextContent)
        error_text = stale.content[0].text
        error = json.loads(error_text[error_text.index("{") :])
        assert error["code"] == SchemaChangedError.code
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        capabilities = _resource_json(
            await client.read_resource("memory://capabilities/current")
        )
        declared_tools = {
            operation["mcp_tool"]
            for operation in capabilities["operations"].values()
            if "mcp_tool" in operation
        }
        assert declared_tools == tool_names
        retention_capability = capabilities["operations"]["retention"]
        assert retention_capability["interfaces"] == ["python", "cli"]
        assert "mcp_tool" not in retention_capability
    assert query_result["rows"][0]["projections"][0]["value"] == "hello"
    assert _tool_json(explained_metric)["metric"]["value"] == 1


def test_query_ir_contract_and_error_registry_are_self_describing(
    m5: tuple[Any, ...],
) -> None:
    application, _, _ = m5
    assert application.status()["ready"] is True
    assert application.validate()["issues"] == []
    contract = query_ir_contract_document(application.schema.fingerprint)
    schema = contract["input_schema"]
    assert schema["properties"]["limit"]["maximum"] == 1000
    assert schema["$defs"]["QueryMatch"]["properties"]["nodes"]["maxItems"] == 8
    for example in contract["examples"]:
        validated = QueryIRDocument.model_validate(example)
        parse_query_ir(validated.model_dump(mode="json", by_alias=True))
    golden = json.loads(
        resource_path("schema", "query-ir-contract.json").read_text(encoding="utf-8")
    )
    assert contract == golden
    assert {
        "eq",
        "ne",
        "lt",
        "lte",
        "gt",
        "gte",
        "in",
        "exists",
    } == QUERY_OPERATORS
    assert set(application.schema.document["query_ir"]["operators"]) == QUERY_OPERATORS
    codes = [item["code"] for item in error_code_registry()]
    assert len(codes) == len(set(codes))
    assert {"invalid_request", "io_error"} <= set(codes)


@pytest.mark.parametrize(
    "document",
    [
        {
            "query_ir_version": "1",
            "match": {"nodes": [{"type": "calls.Session", "alias": "session"}]},
            "return": [{"count": True}],
        },
        {
            "query_ir_version": "1",
            "match": {"nodes": [{"type": "calls.Session", "as": "session"}]},
            "return_": [{"count": True}],
        },
        {
            "query_ir_version": "1",
            "match": {"nodes": [{"type": "x", "as": ""}]},
            "return": [{"count": True}],
        },
        {
            "query_ir_version": "1",
            "match": {
                "nodes": [
                    {"type": "calls.Session", "as": "session"},
                    {"type": "calls.Message", "as": "message"},
                ],
                "edges": [
                    {
                        "type": "session",
                        "from_": "message",
                        "to": "session",
                    }
                ],
            },
            "return": [{"count": True}],
        },
    ],
)
def test_query_ir_model_and_parser_reject_the_same_wire_shape(
    document: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        QueryIRDocument.model_validate(document)
    with pytest.raises(QueryValidationError, match="invalid Query IR"):
        parse_query_ir(document)


def test_query_ir_rejects_disconnected_patterns_and_preserves_optional_edge_key() -> (
    None
):
    disconnected: dict[str, Any] = {
        "query_ir_version": "1",
        "match": {
            "nodes": [
                {"type": "calls.Session", "as": "session"},
                {"type": "calls.Message", "as": "message"},
            ]
        },
        "return": [{"count": True}],
    }
    QueryIRDocument.model_validate(disconnected)
    with pytest.raises(QueryValidationError, match="disconnected"):
        parse_query_ir(disconnected)

    disconnected_cycle = {
        "query_ir_version": "1",
        "match": {
            "nodes": [
                {"type": "graph.A", "as": "a"},
                {"type": "graph.B", "as": "b"},
                {"type": "graph.C", "as": "c"},
            ],
            "edges": [
                {"type": "link", "from": "b", "to": "c"},
                {"type": "link", "from": "c", "to": "b"},
            ],
        },
        "return": [{"count": True}],
    }
    with pytest.raises(QueryValidationError, match="unreachable aliases"):
        parse_query_ir(disconnected_cycle)

    connected = {
        **disconnected,
        "match": {
            **disconnected["match"],
            "edges": [
                {
                    "type": "session",
                    "from": "message",
                    "to": "session",
                    "logical_key": None,
                }
            ],
        },
    }
    plan = parse_query_ir(connected)
    assert plan.edges == ({"type": "session", "from": "message", "to": "session"},)


@pytest.mark.parametrize("resolver", ["import", "declaration", "analysis"])
def test_null_attribute_is_backfilled_for_every_type_resolution_path(
    m5: tuple[Any, ...], tmp_path: Path, resolver: str
) -> None:
    application, _, _ = m5
    _import(
        application,
        _write(
            tmp_path / "first.jsonl",
            [{"id": "s1", "note": None}, {"id": "s2"}],
        ),
        "calls.Session",
    )
    if resolver == "import":
        _import(
            application,
            _write(tmp_path / "second.jsonl", [{"id": "s2", "note": "resolved"}]),
            "calls.Session",
        )
    elif resolver == "declaration":
        application.declare_entity(
            "calls.Session",
            fields={"note": {"type": "string"}},
            contract_fingerprint=application.schema.fingerprint,
        )
    else:
        target = application.execute_query(
            {
                "query_ir_version": "1",
                "match": {"nodes": [{"type": "calls.Session", "as": "session"}]},
                "where": [
                    {
                        "left": {"field": "session.id"},
                        "op": "eq",
                        "right": {"value": "s2"},
                    }
                ],
                "return": [{"field": "session.id"}],
            }
        )["rows"][0]["bindings"]["session"]
        application.write_analytical_attribute(
            target,
            "note",
            "resolved",
            method="test",
            contract_fingerprint=application.schema.fingerprint,
        )
    result = application.execute_query(
        {
            "query_ir_version": "1",
            "match": {"nodes": [{"type": "calls.Session", "as": "session"}]},
            "where": [
                {
                    "left": {"field": "session.note"},
                    "op": "eq",
                    "right": {"value": None},
                }
            ],
            "return": [{"field": "session.id"}],
        }
    )
    assert [row["projections"][0]["value"] for row in result["rows"]] == ["s1"]
