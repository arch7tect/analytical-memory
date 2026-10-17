from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.analytics import (
    AnalyticsError,
    AnalyticsLimitError,
    ObservationUnavailable,
    StaleQueryResult,
)
from analytical_memory.api import MemoryAPI
from analytical_memory.application import MemoryApplication
from analytical_memory.errors import (
    ImportValidationError,
    QueryValidationError,
    RetentionBlockedError,
    SnapshotError,
)
from analytical_memory.ports import MemoryStore
from analytical_memory.retail_quickstart import EXAMPLES, analysis_document, run_retail
from analytical_memory.schema_contract import load_schema


@pytest.fixture
def native(tmp_path: Path, memory_store: MemoryStore) -> MemoryAPI:
    app = MemoryApplication(
        memory_store, FileEvidenceStore(tmp_path / "evidence"), load_schema()
    )
    app.initialize()
    return MemoryAPI(app)


def populate(api: MemoryAPI) -> dict[str, Any]:
    fingerprint = api.application.schema.fingerprint
    for name, entity, key in [
        ("orders", "shop.Order", "order_id"),
        ("tickets", "shop.Ticket", "ticket_id"),
    ]:
        api.jsonl_import(
            EXAMPLES / f"{name}.jsonl",
            entity,
            [{"field": key, "type": "string"}],
            fingerprint,
        )
    join = json.loads((EXAMPLES / "join.json").read_text())
    api.materialize_join(
        join["name"], join["relation"], join["from"], join["to"], fingerprint
    )
    return analysis_document()


def query_result(api: MemoryAPI, query: dict[str, Any]) -> dict[str, Any]:
    return api.native_operation("query_execute_v2", query).result


def capture(api: MemoryAPI, document: dict[str, Any]) -> dict[str, Any]:
    return api.analysis_capture(
        {
            "analysis": document,
            "expected_state": api.data_state().result,
            "definition_version": "native-test-1",
        }
    ).result


def test_retail_full_walkthrough(native: MemoryAPI) -> None:
    result = run_retail(native)
    assert result["replay_revision_unchanged"]
    assert [phase["state"]["data_revision"] for phase in result["phases"]] == [
        0,
        1,
        2,
        3,
        4,
        5,
    ]
    assert result["live_detail"]["total_members"] == 3
    assert result["historical_detail"]["mode"] == "observation_time"


def test_exact_population_pagination_and_distinct_sum(native: MemoryAPI) -> None:
    document = populate(native)
    query = document["members"][0]["document"]
    complete = query_result(native, query)
    assert complete["total_groups"] == 4
    paginated = query_result(native, {**query, "limit": 1, "offset": 1})
    assert paginated["population_hash"] == complete["population_hash"]
    assert paginated["groups"] == complete["groups"][1:2]
    assert paginated["truncated"] and paginated["complete_input"]
    fullsum = copy.deepcopy(query)
    fullsum["measures"][-1].pop("distinct_on")
    group = next(
        row
        for row in query_result(native, fullsum)["groups"]
        if row["key"]["carrier"]["value"] == "FastShip"
        and row["key"]["region"]["value"] == "South"
    )
    assert group["measures"]["affected_order_value"] == 40000
    total = native.analysis_execute(document).result["members"]["totals"]["groups"][0]
    assert total["derived"]["complaint_rate"] == {
        "numerator": 7,
        "denominator": 12,
        "decimal": "0.583333333333",
    }


def test_zero_optional_null_missing_empty_and_unsafe_numbers(
    native: MemoryAPI, tmp_path: Path
) -> None:
    document = populate(native)
    fingerprint = native.application.schema.fingerprint
    source = tmp_path / "extra.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "order_id": "O-113",
                    "carrier": "Empty",
                    "region": None,
                    "amount_cents": None,
                },
                {"order_id": "O-114", "carrier": "Empty", "amount_cents": None},
            ]
        )
        + "\n"
    )
    native.jsonl_import(
        source, "shop.Order", [{"field": "order_id", "type": "string"}], fingerprint
    )
    groups = query_result(native, document["members"][0]["document"])["groups"]
    empty = [row for row in groups if row["key"]["carrier"]["value"] == "Empty"]
    assert {row["key"]["region"]["kind"] for row in empty} == {"null", "missing"}
    assert all(
        row["measures"]["orders"] == 1 and row["measures"]["affected_orders"] == 0
        for row in empty
    )
    query = copy.deepcopy(document["members"][2]["document"])
    query["where"] = [
        {"left": {"field": "o.carrier"}, "op": "eq", "right": {"value": "absent"}}
    ]
    empty_global = query_result(native, query)
    assert empty_global["groups"][0]["derived"]["complaint_rate"]["decimal"] is None
    query["group_by"] = [{"field": "o.carrier", "as": "carrier"}]
    assert query_result(native, query)["groups"] == []
    source.write_text('{"order_id":"O-101","amount_cents":1.5}\n')
    native.jsonl_import(
        source, "shop.Order", [{"field": "order_id", "type": "string"}], fingerprint
    )
    with pytest.raises(AnalyticsError, match="unsafe_numeric"):
        native.analysis_execute(document)


def test_drill_reconciles_repeated_contacts_and_rejects_stale_pages(
    native: MemoryAPI,
) -> None:
    document = populate(native)
    query = document["members"][0]["document"]
    group = next(
        row
        for row in query_result(native, query)["groups"]
        if row["key"]["carrier"]["value"] == "FastShip"
        and row["key"]["region"]["value"] == "South"
    )
    request = {
        "query": query,
        "group_key": group["key"],
        "measure": "complaint_rate",
        "expected_state": native.data_state().result,
        "view": "numerator",
    }
    assert native.query_drill_down(request).result["total_members"] == 1
    assert (
        native.query_drill_down({**request, "view": "denominator"}).result[
            "total_members"
        ]
        == 3
    )
    assert (
        native.query_drill_down(
            {**request, "measure": "delivery_tickets", "view": "counted_entities"}
        ).result["total_members"]
        == 4
    )
    native.jsonl_import(
        EXAMPLES / "correction.jsonl",
        "shop.Ticket",
        [{"field": "ticket_id", "type": "string"}],
        native.application.schema.fingerprint,
    )
    with pytest.raises(StaleQueryResult):
        native.query_drill_down({**request, "offset": 1})
    with pytest.raises(QueryValidationError):
        native.query_drill_down(
            {**request, "expected_state": native.data_state().result, "group_key": {}}
        )


def test_revision_replay_rollback_capture_and_retention(
    native: MemoryAPI, tmp_path: Path
) -> None:
    document = populate(native)
    before = native.data_state().result
    saved = capture(native, document)
    assert native.data_state().result == before
    assert capture(native, document)["replayed"] is True
    for member in document["members"]:
        member["document"]["limit"] = 1
    assert capture(native, document)["id"] == saved["id"]
    native.jsonl_import(
        EXAMPLES / "orders.jsonl",
        "shop.Order",
        [{"field": "order_id", "type": "string"}],
        native.application.schema.fingerprint,
    )
    assert native.data_state().result == before
    bad = tmp_path / "mixed.jsonl"
    bad.write_text(
        '{"order_id":"O-101","amount_cents":20000}\n{"order_id":"O-102","amount_cents":"wrong"}\n'
    )
    with pytest.raises(ImportValidationError):
        native.jsonl_import(
            bad,
            "shop.Order",
            [{"field": "order_id", "type": "string"}],
            native.application.schema.fingerprint,
        )
    assert native.data_state().result == before
    with pytest.raises(RetentionBlockedError):
        native.application.memory_store.release_retention(
            saved["manifest_digest"], released_at="2026-10-17T00:00:00Z", reason="test"
        )
    assert native.application.current_metric("native-test-1", {})["metric"] is None
    native.application.evidence_store.remove(saved["manifest_digest"])
    with pytest.raises(ObservationUnavailable):
        native.analysis_read({"observation_id": saved["id"]})
    with pytest.raises(SnapshotError):
        native.application.snapshot_create(tmp_path / "missing.zip")


def test_snapshot_and_transfer_restore_historical_values(
    native: MemoryAPI, tmp_path: Path
) -> None:
    document = populate(native)
    saved = capture(native, document)
    for kind in ["snapshot", "transfer"]:
        source = tmp_path / f"{kind}.artifact"
        if kind == "snapshot":
            native.application.snapshot_create(source)
        else:
            native.application.transfer_export(source)
        app = MemoryApplication(
            SqliteMemoryStore(tmp_path / f"{kind}.db"),
            FileEvidenceStore(tmp_path / f"{kind}-evidence"),
            load_schema(),
        )
        if kind == "snapshot":
            app.snapshot_import(source)
        else:
            app.transfer_import(source)
        api = MemoryAPI(app)
        assert api.data_state().result["data_revision"] == 0
        assert api.data_state().result["generation"] != saved["generation"]
        assert (
            api.analysis_read({"observation_id": saved["id"]}).result["observation"][
                "freshness"
            ]
            == "unknown"
        )
        result = api.analysis_execute(document).result
        assert result["members"]["totals"]["groups"][0]["measures"]["orders"] == 12
        fresh = capture(api, document)
        assert fresh["id"] != saved["id"]
        assert api.analysis_read(
            {"observation_id": fresh["id"], "fresh_only": True}
        ).result["verified"]


def test_inspection_reports_lifecycle_keys_and_coverage(
    native: MemoryAPI, tmp_path: Path
) -> None:
    document = populate(native)
    result = native.analysis_execute(document).result
    inspection = result["members"]["unattributed_reasons"]
    assert inspection["total_sources"] == 12
    assert inspection["reasons"] == {
        "linked": 10,
        "no_target": 1,
        "missing_or_null_key": 1,
    }
    records = native.application.memory_store.snapshot_records()
    first_ticket = next(
        row["node_id"]
        for row in records["node_attribute"]
        if row["attribute_name"] == "ticket_id"
        and json.loads(row["value_json"]) == "T01"
    )
    relation = next(
        row for row in records["relation"] if row["source_node_id"] == first_ticket
    )
    native.application.deactivate_relation(relation["id"])
    request = {"name": "ticket_to_order", "expected_state": native.data_state().result}
    assert native.relation_inspect(request).result["reasons"]["inactive_relation"] == 1
    source = tmp_path / "key-change.jsonl"
    source.write_text('{"ticket_id":"T02","order_id":"O-103"}\n')
    native.jsonl_import(
        source,
        "shop.Ticket",
        [{"field": "ticket_id", "type": "string"}],
        native.application.schema.fingerprint,
    )
    reasons = native.relation_inspect(
        {**request, "expected_state": native.data_state().result}
    ).result["reasons"]
    assert reasons["active_keys_disagree"] >= 1


def test_native_privacy_rejects_filter_dependency_export(native: MemoryAPI) -> None:
    document = populate(native)
    saved = capture(native, document)
    assert native.analysis_read({"observation_id": saved["id"], "public": True}).result[
        "verified"
    ]
    native.declare_entity(
        "shop.Ticket",
        "public",
        {"issue_code": {"type": "string", "privacy": "private"}},
        native.application.schema.fingerprint,
    )
    with pytest.raises(ObservationUnavailable):
        native.analysis_read({"observation_id": saved["id"], "public": True})
    private = capture(native, document)
    assert private["privacy_class"] == "private"
    with pytest.raises(ObservationUnavailable):
        native.analysis_read({"observation_id": private["id"], "public": True})


def test_budget_and_invalid_contracts_fail_closed(
    native: MemoryAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = populate(native)
    import analytical_memory.analytics as analytics

    monkeypatch.setattr(analytics, "MAX_BINDINGS", 1)
    with pytest.raises(AnalyticsLimitError):
        native.analysis_execute(document)
    query = copy.deepcopy(document["members"][0]["document"])
    query["optional_match"][0]["edges"][0].pop("logical_key")
    with pytest.raises(QueryValidationError):
        native.native_operation("query_execute_v2", query)


def test_verified_legacy_snapshot_restores_without_reset(native: MemoryAPI) -> None:
    source = Path(__file__).parent / "fixtures" / "legacy-0.6.1.zip"
    native.application.snapshot_import(source)
    state = native.data_state().result
    assert state["data_revision"] == 0
    records = native.application.memory_store.snapshot_records()
    assert len(records["node"]) == 1
    assert any(
        json.loads(row["value_json"]) == "legacy-order"
        for row in records["node_attribute"]
    )
    assert records["analysis_observation"] == []
    assert native.application.validate()["issues"] == []


def test_capture_noop_declarations_and_manifest_metadata_integrity(
    native: MemoryAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = populate(native)
    fingerprint = native.application.schema.fingerprint
    native.declare_entity(
        "shop.Order", "public", {"amount_cents": {"type": "number"}}, fingerprint
    )
    saved = capture(native, document)
    before = native.data_state().result
    native.declare_entity(
        "shop.Order", "public", {"amount_cents": {"type": "number"}}, fingerprint
    )
    assert native.data_state().result == before
    assert capture(native, document)["replayed"]
    native.declare_namespace("shop", "Retail example", fingerprint)
    saved = capture(native, document)
    before = native.data_state().result
    native.declare_namespace("shop", "Retail example", fingerprint)
    assert native.data_state().result == before
    assert capture(native, document)["replayed"]
    import analytical_memory.native_store as native_store
    from analytical_memory.analytics import AnalyticsIntegrityError

    original = native_store.observation

    def tampered(connection: Any, observation_id: str) -> dict[str, Any]:
        return {**original(connection, observation_id), "data_revision": 999}

    monkeypatch.setattr(native_store, "observation", tampered)
    with pytest.raises(AnalyticsIntegrityError):
        native.analysis_read({"observation_id": saved["id"]})


def test_capture_commit_failure_cleans_exclusive_manifest(
    native: MemoryAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    document = populate(native)
    store: Any = native.application.memory_store
    before_state = native.data_state().result
    before_files = native.application.evidence_store.list_digests(1000)
    original = store._write_connection
    fail_once = True

    @contextmanager
    def fail_commit(**kwargs: Any) -> Iterator[Any]:
        nonlocal fail_once
        with original(**kwargs) as connection:
            yield connection
            if fail_once:
                fail_once = False
                raise RuntimeError("injected commit failure")

    monkeypatch.setattr(store, "_write_connection", fail_commit)
    with pytest.raises(RuntimeError, match="injected commit"):
        capture(native, document)
    assert native.application.evidence_store.list_digests(1000) == before_files
    assert native.data_state().result == before_state
    assert store.snapshot_records()["analysis_observation"] == []
    assert capture(native, document)["replayed"] is False


def test_read_bundle_and_capture_are_consistent_with_concurrent_writer(
    native: MemoryAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import analytical_memory.native_store as native_store

    document = populate(native)
    entered, release = Event(), Event()
    from analytical_memory.analytics import execute_analysis

    original = execute_analysis

    def paused(
        facts: dict[str, Any], request: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        entered.set()
        assert release.wait(5)
        return original(facts, request, **kwargs)

    monkeypatch.setattr(native_store, "execute_analysis", paused)
    expected = native.data_state().result
    with ThreadPoolExecutor(max_workers=2) as pool:
        read = pool.submit(native.analysis_execute, document)
        assert entered.wait(5)
        native.jsonl_import(
            EXAMPLES / "correction.jsonl",
            "shop.Ticket",
            [{"field": "ticket_id", "type": "string"}],
            native.application.schema.fingerprint,
        )
        release.set()
        result = read.result(timeout=5).result
    assert result["state"] == expected
    assert (
        result["members"]["totals"]["groups"][0]["measures"]["delivery_tickets"] == 10
    )
    assert native.data_state().result["data_revision"] == expected["data_revision"] + 1
    entered.clear()
    release.clear()
    request = {
        "analysis": document,
        "expected_state": native.data_state().result,
        "definition_version": "race-test",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        saved_future = pool.submit(native.analysis_capture, request)
        assert entered.wait(5)
        writer = pool.submit(
            native.jsonl_import,
            EXAMPLES / "enrichment.jsonl",
            "shop.Order",
            [{"field": "order_id", "type": "string"}],
            native.application.schema.fingerprint,
        )
        assert not writer.done()
        release.set()
        saved = saved_future.result(timeout=5).result
        writer.result(timeout=5)
    assert (
        native.analysis_read({"observation_id": saved["id"]}).result["observation"][
            "freshness"
        ]
        == "potentially_stale"
    )


def test_parallel_edges_and_sum_detail_contributions(native: MemoryAPI) -> None:
    document = populate(native)
    join = json.loads((EXAMPLES / "join.json").read_text())
    native.materialize_join(
        "second_ticket_order",
        join["relation"],
        join["from"],
        join["to"],
        native.application.schema.fingerprint,
    )
    query = {
        "query_ir_version": "2",
        "match": {
            "nodes": [
                {"type": "shop.Order", "as": "o"},
                {"type": "shop.Ticket", "as": "t"},
            ],
            "edges": [{"type": "order", "from": "t", "to": "o"}],
        },
        "measures": [
            {"as": "bindings", "op": "count", "node": "t"},
            {"as": "tickets", "op": "count_distinct", "node": "t"},
        ],
    }
    measures = query_result(native, query)["groups"][0]["measures"]
    assert measures == {"bindings": 28, "tickets": 14}
    aggregate = document["members"][0]["document"]
    south = next(
        group
        for group in query_result(native, aggregate)["groups"]
        if group["key"]["carrier"]["value"] == "FastShip"
        and group["key"]["region"]["value"] == "South"
    )
    detail = native.query_drill_down(
        {
            "query": aggregate,
            "group_key": south["key"],
            "measure": "affected_order_value",
            "expected_state": native.data_state().result,
        }
    ).result
    assert detail["total_members"] == 1
    assert detail["group_id"] == south["group_id"]
    contribution = next(iter(detail["reconciliation"]["sum_contributions"].values()))
    assert contribution == {"value": 10000, "occurrences": 4, "contribution": 10000}


def test_safe_integer_overflow_and_query_field_types(
    native: MemoryAPI, tmp_path: Path
) -> None:
    document = populate(native)
    query = copy.deepcopy(document["members"][0]["document"])
    query["where"] = [
        {"left": {"field": "o.carrier"}, "op": "eq", "right": {"value": 123}}
    ]
    with pytest.raises(QueryValidationError, match="field type"):
        query_result(native, query)
    query["where"] = [{"left": {"field": "o.absent"}, "op": "exists"}]
    with pytest.raises(QueryValidationError, match="unknown field"):
        query_result(native, query)
    patch = tmp_path / "unsafe.jsonl"
    patch.write_text('{"order_id":"O-101","amount_cents":9007199254740991}\n')
    native.jsonl_import(
        patch,
        "shop.Order",
        [{"field": "order_id", "type": "string"}],
        native.application.schema.fingerprint,
    )
    with pytest.raises(AnalyticsError, match="unsafe_numeric"):
        native.analysis_execute(document)


def test_referenced_existing_manifest_survives_failed_capture(
    native: MemoryAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    document = populate(native)
    evidence: Any = native.application.evidence_store
    original_put = evidence.put_tracked
    preserved = []

    def existing(source: Path, expected: Any) -> Any:
        result = original_put(source, expected)
        preserved.append(expected.digest)
        return replace(result, created=False)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(evidence, "put_tracked", existing)
    monkeypatch.setattr(
        native.application.memory_store, "_upsert_provenance_entities", fail
    )
    with pytest.raises(RuntimeError, match="injected write"):
        capture(native, document)
    assert len(preserved) == 1
    assert evidence.stat(preserved[0]).availability == "present"


def test_legacy_transfer_adapter_and_new_import_generation(native: MemoryAPI) -> None:
    before = native.data_state().result
    source = Path(__file__).parent / "fixtures" / "legacy-0.6.1.json"
    native.application.transfer_import(source)
    assert native.data_state().result["generation"] != before["generation"]
    assert native.data_state().result["data_revision"] == 0
    assert len(native.application.memory_store.snapshot_records()["node"]) == 1


def test_saved_detail_reports_missing_raw_source_without_losing_values(
    native: MemoryAPI,
) -> None:
    document = populate(native)
    saved = capture(native, document)
    group = query_result(native, document["members"][0]["document"])["groups"][0]
    records = native.application.memory_store.snapshot_records()
    fragment_id = next(
        row["fragment_id"]
        for row in records["node_attribute"]
        if row["attribute_name"] == "amount_cents"
    )
    object_id = next(
        row["evidence_object_id"]
        for row in records["evidence_fragment"]
        if row["id"] == fragment_id
    )
    raw = next(row for row in records["evidence_object"] if row["id"] == object_id)
    native.application.evidence_store.remove(raw["digest"])
    detail = native.query_drill_down(
        {
            "observation_id": saved["id"],
            "query_name": "by_carrier_region",
            "group_key": group["key"],
            "measure": "affected_orders",
        }
    ).result
    assert detail["total_members"] == 3
    assert any(
        row["availability"] == "missing" for row in detail["raw_source_evidence"]
    )
    assert native.analysis_read({"observation_id": saved["id"]}).result["verified"]


def test_integer_valued_numbers_exact_ratio_order_and_nulls_last(
    native: MemoryAPI, tmp_path: Path
) -> None:
    populate(native)
    patch = tmp_path / "ratio-input.jsonl"
    patch.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"order_id": "O-101", "amount_cents": 9007199254740991},
                {"order_id": "O-102", "amount_cents": 9007199254740990},
                {"order_id": "O-103", "amount_cents": 0},
                {"order_id": "O-104", "amount_cents": 1.0},
            ]
        )
        + "\n"
    )
    native.jsonl_import(
        patch,
        "shop.Order",
        [{"field": "order_id", "type": "string"}],
        native.application.schema.fingerprint,
    )
    query: dict[str, Any] = {
        "query_ir_version": "2",
        "match": {"nodes": [{"type": "shop.Order", "as": "o"}]},
        "group_by": [{"field": "o.order_id", "as": "order_id"}],
        "measures": [
            {"as": "one", "op": "count_distinct", "node": "o"},
            {"as": "price", "op": "sum", "field": "o.amount_cents", "distinct_on": "o"},
        ],
        "derive": [
            {"as": "rate", "op": "ratio", "numerator": "one", "denominator": "price"}
        ],
        "order_by": [{"result": "rate", "direction": "desc"}],
    }
    desc = query_result(native, query)["groups"]
    identifiers = [row["key"]["order_id"]["value"] for row in desc]
    assert identifiers.index("O-102") < identifiers.index("O-101")
    assert identifiers[-1] == "O-103"
    assert (
        next(row for row in desc if row["key"]["order_id"]["value"] == "O-104")[
            "measures"
        ]["price"]
        == 1
    )
    query["order_by"][0]["direction"] = "asc"
    identifiers = [
        row["key"]["order_id"]["value"] for row in query_result(native, query)["groups"]
    ]
    assert identifiers.index("O-101") < identifiers.index("O-102")
    assert identifiers[-1] == "O-103"


def test_capture_retains_binding_and_deduplication_maps(native: MemoryAPI) -> None:
    document = populate(native)
    saved = capture(native, document)
    provider = native.application.evidence_store
    status = provider.stat(saved["manifest_digest"])
    assert status.byte_size is not None
    manifest = json.loads(provider.read(saved["manifest_digest"], 0, status.byte_size))
    assert manifest["contract_fingerprint"] == native.application.schema.fingerprint
    groups = query_result(native, document["members"][0]["document"])["groups"]
    south = next(
        group
        for group in groups
        if group["key"]["carrier"]["value"] == "FastShip"
        and group["key"]["region"]["value"] == "South"
    )
    membership = manifest["membership"]["by_carrier_region"][south["group_id"]]
    assert len(membership["bindings"]) == 6
    assert len(membership["measures"]["orders"]["node_ids"]) == 3
    assert len(membership["measures"]["affected_orders"]["node_ids"]) == 1
    assert len(membership["measures"]["delivery_tickets"]["node_ids"]) == 4


def test_sum_cancellation_is_exact_and_independent_of_binding_order(
    native: MemoryAPI, tmp_path: Path
) -> None:
    populate(native)
    patch = tmp_path / "cancellation.jsonl"
    patch.write_text(
        "\n".join(
            json.dumps({"order_id": f"O-{101 + index}", "amount_cents": value})
            for index, value in enumerate(
                [9007199254740991, 9007199254740991, -9007199254740991, -90000]
            )
        )
        + "\n"
    )
    native.jsonl_import(
        patch,
        "shop.Order",
        [{"field": "order_id", "type": "string"}],
        native.application.schema.fingerprint,
    )
    query = {
        "query_ir_version": "2",
        "match": {"nodes": [{"type": "shop.Order", "as": "o"}]},
        "measures": [{"as": "total", "op": "sum", "field": "o.amount_cents"}],
    }
    assert (
        query_result(native, query)["groups"][0]["measures"]["total"]
        == 9007199254730991
    )


def test_populated_pre_native_database_upgrades_additively(
    memory_store: MemoryStore, tmp_path: Path
) -> None:
    import shutil

    from analytical_memory.resources import resource_path

    backend = memory_store.status().backend
    migrations = tmp_path / "old-migrations"
    shutil.copytree(resource_path("migrations", backend), migrations)
    manifest_path = migrations / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["migrations"] = manifest["migrations"][:-1]
    if "schema_version" in manifest:
        manifest["schema_version"] = 9
    manifest_path.write_text(json.dumps(manifest))
    store: Any = memory_store
    statement = (
        "INSERT INTO node (id, namespace, type, display_label, privacy_class, "
        "recorded_at, updated_at) VALUES ('retained', 'legacy', 'Item', NULL, "
        "'public', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    if backend == "sqlite":
        from analytical_memory.sqlite_migrations import migrate_sqlite

        connection = store._connect(require_initialized=False)
        migrate_sqlite(connection, migrations)
        with connection:
            connection.execute(statement)
        connection.close()
    else:
        from analytical_memory.postgresql_migrations import migrate_postgresql

        connection = store._raw_connect()
        migrate_postgresql(connection, migrations)
        connection.execute(statement)
        connection.commit()
        connection.close()
    store.initialize()
    assert store.snapshot_records()["node"][0]["id"] == "retained"
    assert store.integrity()["ok"]
    assert store.analytics_operation("data_state", {})["data_revision"] == 0


def test_status_read_retains_freshness_privacy_and_integrity_gates(
    native: MemoryAPI,
) -> None:
    document = populate(native)
    saved = capture(native, document)
    request = {"observation_id": saved["id"], "view": "status"}
    status = native.analysis_read({**request, "public": True}).result
    assert status["verified"] and "results" not in status
    assert status["observation"]["freshness"] == "current"
    native.declare_entity(
        "shop.Ticket",
        "public",
        {"issue_code": {"type": "string", "privacy": "private"}},
        native.application.schema.fingerprint,
    )
    assert (
        native.analysis_read(request).result["observation"]["freshness"]
        == "potentially_stale"
    )
    with pytest.raises(StaleQueryResult):
        native.analysis_read({**request, "fresh_only": True})
    with pytest.raises(ObservationUnavailable):
        native.analysis_read({**request, "public": True})

    evidence = native.application.evidence_store
    assert isinstance(evidence, FileEvidenceStore)
    path = evidence.object_path(saved["manifest_digest"])
    # The fixture's unique manifest is deliberately corrupted to test the read gate.
    path.write_bytes(b"corrupt test manifest")
    with pytest.raises(ObservationUnavailable, match="failed verification"):
        native.analysis_read(request)


def test_compact_preserves_null_missing_and_binding_alias(
    native: MemoryAPI, tmp_path: Path
) -> None:
    from analytical_memory.api_models import QueryIRResponse
    from analytical_memory.mcp_operations import QueryOperationResponse
    from analytical_memory.response_views import compact_drill, compact_query

    source = tmp_path / "values.jsonl"
    source.write_text(
        '{"id":"null","value":null}\n{"id":"missing"}\n{"id":"present","value":3}\n'
    )
    native.jsonl_import(
        source,
        "demo.Item",
        [{"field": "id", "type": "string"}],
        native.application.schema.fingerprint,
    )
    result = native.execute_query(
        {
            "query_ir_version": "1",
            "match": {"nodes": [{"type": "demo.Item", "as": "node"}]},
            "return": [{"field": "node.id"}, {"field": "node.value"}],
        }
    )
    assert isinstance(result, QueryIRResponse)
    for full in (
        result,
        result.model_copy(update={"rows": [], "count": None}),
        result.model_copy(update={"rows": [], "count": 0}),
    ):
        assert isinstance(
            QueryOperationResponse.model_validate(full.model_dump(mode="json")).root,
            QueryIRResponse,
        )
        compact = compact_query(full)
        assert (
            QueryOperationResponse.model_validate(compact.model_dump(mode="json")).root
            == compact
        )
    rows = {
        row.projections[0].value: row.projections[1]
        for row in compact_query(result).rows
    }
    assert rows["null"].value is None and rows["null"].record_id is not None
    assert rows["missing"].value is None and rows["missing"].record_id is None
    assert rows["present"].value == 3
    query = {
        "query_ir_version": "2",
        "match": {"nodes": [{"type": "demo.Item", "as": "node"}]},
        "measures": [{"as": "items", "op": "count_distinct", "node": "node"}],
    }
    aggregate = query_result(native, query)
    detail = native.query_drill_down(
        {
            "query": query,
            "expected_state": aggregate["state"],
            "group_key": {},
            "measure": "items",
            "view": "bindings",
        }
    ).result
    assert compact_drill(detail)["rows"] == detail["rows"]
