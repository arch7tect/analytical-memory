from __future__ import annotations

import json
import os
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters
from mcp.types import TextContent

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
        return dict(result.structured_content)
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


def test_ambiguous_import_rolls_back_and_compensates_evidence(
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
    assert not object_path.exists()

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
    assert set((evidence_root / "objects" / "sha256").glob("*/*")) == objects_before


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
    application.declare_entity(
        "calls.Session",
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
    manifest = application.snapshot_create(snapshot)
    restored = MemoryApplication(
        SqliteMemoryStore(tmp_path / "restored.db"),
        FileEvidenceStore(tmp_path / "restored-evidence"),
        schema,
    )
    result = restored.snapshot_import(snapshot)
    assert result["snapshot_id"] == manifest["snapshot_id"]
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
    capsys.readouterr()
    assert main([*shared, "ontology", "describe"]) == 0
    ontology = json.loads(capsys.readouterr().out)
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
        declaration = await client.call_tool(
            "memory_ontology_declare_entity",
            {
                "entity_type": "calls.Session",
                "contract_fingerprint": fingerprint,
                "fields": {
                    "id": {"type": "string", "required": True},
                    "note": {"type": "string"},
                },
            },
        )
        assert declaration.is_error is False
        for path, entity_type in (
            (sessions, "calls.Session"),
            (messages, "calls.SessionMessage"),
        ):
            imported = await client.call_tool(
                "memory_jsonl_import",
                {
                    "source_path": str(path),
                    "entity_type": entity_type,
                    "key": [{"field": "id", "type": "string"}],
                    "contract_fingerprint": fingerprint,
                },
            )
            assert imported.is_error is False
        session_query = await client.call_tool(
            "memory_query_execute",
            {
                "document": {
                    "query_ir_version": "1",
                    "match": {"nodes": [{"type": "calls.Session", "as": "session"}]},
                    "return": [{"field": "session.id"}],
                }
            },
        )
        session_node_id = _tool_json(session_query)["rows"][0]["bindings"]["session"]
        null_query = await client.call_tool(
            "memory_query_execute",
            {
                "document": {
                    "query_ir_version": "1",
                    "match": {"nodes": [{"type": "calls.Session", "as": "session"}]},
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
        )
        assert len(_tool_json(null_query)["rows"]) == 1
        written = await client.call_tool(
            "memory_attribute_write_analysis",
            {
                "node_id": session_node_id,
                "attribute_name": "classification",
                "value": "excellent",
                "method": "mcp-test-v1",
                "contract_fingerprint": fingerprint,
            },
        )
        assert _tool_json(written)["attribute_id"]
        joined = await client.call_tool(
            "memory_join_materialize",
            {
                "name": "message_to_session",
                "relation": "session",
                "from_": {"type": "calls.SessionMessage", "fields": ["session_id"]},
                "to": {"type": "calls.Session", "fields": ["id"]},
                "contract_fingerprint": fingerprint,
                "idempotency_key": "mcp-join",
            },
        )
        assert _tool_json(joined)["created_relations"] == 1
        queried = await client.call_tool(
            "memory_query_execute",
            {
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
        )
        query_result = _tool_json(queried)
        message_node_id = query_result["rows"][0]["bindings"]["message"]
        traversed = await client.call_tool(
            "memory_traverse_relations",
            {"start_node_id": message_node_id, "direction": "outbound"},
        )
        relation_id = _tool_json(traversed)["edges"][0]["relation_id"]
        corrected = await client.call_tool(
            "memory_relation_deactivate", {"relation_id": relation_id}
        )
        assert _tool_json(corrected)["active"] is False
        metric = await client.call_tool(
            "memory_metric_write_analysis",
            {
                "definition_version": "message-count-v1",
                "value": 1,
                "dimensions": {"entity": "SessionMessage"},
                "method": "count-v1",
                "method_version": "1",
                "contract_fingerprint": fingerprint,
            },
        )
        metric_id = _tool_json(metric)["metric_id"]
        explained_metric = await client.call_tool(
            "memory_explain_metric", {"metric_id": metric_id}
        )
        deleted = await client.call_tool(
            "memory_node_delete", {"node_id": message_node_id}
        )
        assert _tool_json(deleted)["nodes"] == 1
        stale = await client.call_tool(
            "memory_ontology_declare_entity",
            {
                "entity_type": "calls.Other",
                "contract_fingerprint": "stale",
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
