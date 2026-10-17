"""Human walkthrough using public application operations exclusively."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.api import MemoryAPI
from analytical_memory.application import MemoryApplication
from analytical_memory.resources import resource_path
from analytical_memory.schema_contract import load_schema

EXAMPLES = resource_path("examples", "retail")


def analysis_document() -> dict[str, Any]:
    return dict(json.loads((EXAMPLES / "analysis.json").read_text()))


def run_retail(api: MemoryAPI) -> dict[str, Any]:
    """Run on a new, empty memory supplied by the caller; retain its evidence."""
    app = api.application
    fingerprint = app.schema.fingerprint
    phases = []

    def record(name: str) -> None:
        ontology = api.ontology().model_dump(mode="json")
        phases.append(
            {
                "phase": name,
                "state": api.data_state().result,
                "ontology_fingerprint": ontology["ontology_fingerprint"],
                "ontology": ontology["document"],
            }
        )

    record("empty")
    if app.memory_store.lifecycle_state()["nodes"]:
        raise ValueError("retail walkthrough requires a dedicated empty memory")
    for name, entity, key_field in [
        ("orders", "shop.Order", "order_id"),
        ("tickets", "shop.Ticket", "ticket_id"),
    ]:
        api.jsonl_import(
            EXAMPLES / f"{name}.jsonl",
            entity,
            [{"field": key_field, "type": "string"}],
            fingerprint,
        )
        record(name)
    join = json.loads((EXAMPLES / "join.json").read_text())
    joined = api.materialize_join(
        join["name"], join["relation"], join["from"], join["to"], fingerprint
    ).model_dump(mode="json")
    record("linked")
    linked = api.execute_query(
        json.loads((EXAMPLES / "linked-query.json").read_text())
    ).model_dump(mode="json")
    assert len(linked["rows"]) == 10
    document = analysis_document()
    initial = api.analysis_execute(document).result
    totals = initial["members"]["totals"]["groups"][0]
    assert totals["measures"] == {
        "orders": 12,
        "delivery_tickets": 10,
        "affected_orders": 7,
        "affected_order_value": 70000,
    }
    assert initial["coverage"] == {
        "imported_tickets": 16,
        "delivery_tickets": 12,
        "attributed": 10,
        "unattributed": 2,
    }
    capture = {
        "analysis": document,
        "expected_state": initial["state"],
        "definition_version": "retail-delivery-1",
    }
    saved = api.analysis_capture(capture).result
    key = {
        "carrier": {"kind": "value", "type": "string", "value": "EcoPost"},
        "region": {"kind": "value", "type": "string", "value": "South"},
    }
    detail = {
        "query": document["members"][0]["document"],
        "group_key": key,
        "measure": "affected_orders",
        "expected_state": initial["state"],
    }
    live = api.query_drill_down(detail).result
    assert live["total_members"] == 3
    assert {
        next(
            attr["value"]
            for attr in row["attributes"]
            if attr["attribute_name"] == "order_id"
        )
        for row in live["rows"]
    } == {"O-110", "O-111", "O-112"}
    api.jsonl_import(
        EXAMPLES / "enrichment.jsonl",
        "shop.Order",
        [{"field": "order_id", "type": "string"}],
        fingerprint,
    )
    record("warehouse_enrichment")
    enriched = api.analysis_execute(document).result
    stale_after_enrichment = api.analysis_read({"observation_id": saved["id"]}).result
    assert stale_after_enrichment["observation"]["freshness"] == "potentially_stale"
    assert enriched["members"]["totals"]["groups"][0]["measures"] == totals["measures"]
    enriched_saved = api.analysis_capture(
        {**capture, "expected_state": enriched["state"]}
    ).result
    api.jsonl_import(
        EXAMPLES / "correction.jsonl",
        "shop.Ticket",
        [{"field": "ticket_id", "type": "string"}],
        fingerprint,
    )
    record("ticket_correction")
    corrected = api.analysis_execute(document).result
    assert (
        corrected["members"]["totals"]["groups"][0]["measures"]["delivery_tickets"]
        == 11
    )
    assert corrected["coverage"]["delivery_tickets"] == 13
    assert phases[-1]["ontology_fingerprint"] == phases[-2]["ontology_fingerprint"]
    historical = api.query_drill_down(
        {
            "observation_id": saved["id"],
            "query_name": "by_carrier_region",
            "group_key": key,
            "measure": "delivery_tickets",
        }
    ).result
    assert historical["total_members"] == 3
    final_saved = api.analysis_capture(
        {**capture, "expected_state": corrected["state"]}
    ).result
    replay_state = api.data_state().result
    api.jsonl_import(
        EXAMPLES / "correction.jsonl",
        "shop.Ticket",
        [{"field": "ticket_id", "type": "string"}],
        fingerprint,
    )
    no_edge = api.materialize_join(
        join["name"], join["relation"], join["from"], join["to"], fingerprint
    ).model_dump(mode="json")
    assert api.data_state().result == replay_state
    assert no_edge["created_relations"] == 0
    return {
        "format_version": "2",
        "ok": True,
        "case": "retail-delivery",
        "contract_fingerprint": fingerprint,
        "phases": phases,
        "join": joined,
        "linked_query": linked,
        "initial": initial,
        "live_detail": live,
        "saved": saved,
        "enriched": enriched,
        "enriched_saved": enriched_saved,
        "corrected": corrected,
        "historical_detail": historical,
        "final_saved": final_saved,
        "replay_revision_unchanged": True,
    }


def run_isolated_retail(*, extensions: bool = False) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="analytical-memory-retail-") as raw:
        root = Path(raw)
        app = MemoryApplication(
            SqliteMemoryStore(root / "memory.db"),
            FileEvidenceStore(root / "evidence"),
            load_schema(),
        )
        app.initialize()
        api = MemoryAPI(app)
        result = run_retail(api)
        if extensions:
            result["extensions"] = run_extensions(api)
        return result


def human_report(result: dict[str, Any]) -> str:
    lines = [
        ("Retail delivery: from separate datasets to explainable conclusions"),
        "",
        (
            "1. Import 12 orders, then 16 support contacts: 28 nodes"
            ", no implicit relations."
        ),
        (
            "2. Explicitly link tickets to orders: 14 edges; one unk"
            "nown and one missing key."
        ),
        ("3. Analyse delivery contacts in one consistent snapshot:"),
        "",
        (
            "Carrier / region | Orders | Contacts | Affected orders "
            "| Rate | Affected value (cents)"
        ),
    ]
    for group in result["initial"]["members"]["by_carrier_region"]["groups"]:
        key, measures, ratio = (
            group["key"],
            group["measures"],
            group["derived"]["complaint_rate"],
        )
        lines.append(
            f"{key['carrier']['value']} / {key['region']['value']} | "
            f"{measures['orders']} | {measures['delivery_tickets']} | "
            f"{measures['affected_orders']} | "
            f"{ratio['numerator']}/{ratio['denominator']} | "
            f"{measures['affected_order_value']}"
        )
    lines += [
        "",
        (
            "Both carriers have 5 delivery contacts, but 2 FastShip "
            "orders and 5 EcoPost orders are affected."
        ),
        (
            "EcoPost South has 3 of 3 known orders affected. Drill-d"
            "own identifies O-110, O-111 and O-112 with source prove"
            "nance."
        ),
        (
            "Across the known-order population: 7/12 affected; 70000"
            " cents of affected order value."
        ),
        (
            "Coverage: 16 imported contacts, 12 delivery contacts, 1"
            "0 attributed and 2 unattributed."
        ),
        ("This synthetic sample shows association, not causality or revenue loss."),
        "",
        ("4. Capture the analysis and its immutable input values."),
        (
            "5. Add warehouse to existing orders: ontology grows, ID"
            "s and edges survive; prior observations become stale."
        ),
        (
            "6. Recalculate and capture. Correct T14 from billing to"
            " late_delivery: ontology stays the same, revision advan"
            "ces."
        ),
        (
            "   Delivery contacts become 11 attributed / 13 total; a"
            "ffected orders and value stay unchanged."
        ),
        (
            "7. Historical drill-down retains the original 3 EcoPost"
            " South contacts; a new capture records 4."
        ),
        (
            "8. Exact import replay and a fresh no-edge join leave t"
            "he fact revision unchanged."
        ),
        "",
        (
            "Structural contract stays fixed throughout. Ontology de"
            "scribes shape; generation/revision guards actual data."
        ),
        (
            "All calculations, coverage and drill-down run inside An"
            "alytical Memory; the walkthrough only verifies and pres"
            "ents them."
        ),
    ]
    if "extensions" in result:
        lines += [
            "",
            "Optional checks passed: explicit incremental join; "
            "atomic type rollback; local text search; "
            "private capture public-use rejection; "
            "snapshot restore with unknown freshness.",
        ]
    return "\n".join(lines)


def run_extensions(api: MemoryAPI) -> dict[str, Any]:
    """Optional checks after the core walkthrough; no commercial provider needed."""
    from analytical_memory.analytics import ObservationUnavailable
    from analytical_memory.errors import ImportValidationError

    fingerprint = api.application.schema.fingerprint
    document = analysis_document()
    with tempfile.TemporaryDirectory(prefix="analytical-memory-extensions-") as raw:
        root = Path(raw)
        ticket = root / "extra-ticket.jsonl"
        ticket.write_text(
            '{"ticket_id":"T17","order_id":"O-103",'
            '"issue_code":"late_delivery","message":"The parcel arrived late."}\n'
        )
        api.jsonl_import(
            ticket,
            "shop.Ticket",
            [{"field": "ticket_id", "type": "string"}],
            fingerprint,
        )
        before_join = api.analysis_execute(document).result
        assert before_join["coverage"]["unattributed"] == 3
        join = json.loads((EXAMPLES / "join.json").read_text())
        joined = api.materialize_join(
            join["name"], join["relation"], join["from"], join["to"], fingerprint
        ).model_dump(mode="json")
        assert joined["created_relations"] == 1
        after_join = api.analysis_execute(document).result
        assert after_join["coverage"]["attributed"] == 12
        invalid = root / "invalid-patch.jsonl"
        invalid.write_text(
            '{"order_id":"O-101","amount_cents":20000}\n{"order_id":"O-102","amount_cents":"wrong"}\n'
        )
        before = api.data_state().result
        try:
            api.jsonl_import(
                invalid,
                "shop.Order",
                [{"field": "order_id", "type": "string"}],
                fingerprint,
            )
        except ImportValidationError:
            pass
        else:
            raise RuntimeError("mixed-type patch should fail atomically")
        assert api.data_state().result == before
        api.declare_entity(
            "shop.Ticket",
            "public",
            {"message": {"type": "string", "searchable": True}},
            fingerprint,
        )
        search = api.application.search_text("parcel", limit=20)
        assert len(search["results"]) == 1
        api.declare_entity(
            "shop.Ticket",
            "public",
            {
                "issue_code": {"type": "string", "privacy": "private"},
                "message": {"type": "string", "searchable": True},
            },
            fingerprint,
        )
        computed = api.analysis_execute(document).result
        private = api.analysis_capture(
            {
                "analysis": document,
                "expected_state": computed["state"],
                "definition_version": "retail-extensions-1",
            }
        ).result
        try:
            api.analysis_read({"observation_id": private["id"], "public": True})
        except ObservationUnavailable:
            pass
        else:
            raise RuntimeError("private capture must not pass native public-use gates")
        snapshot = root / "snapshot.zip"
        api.application.snapshot_create(snapshot)
        restored = MemoryApplication(
            SqliteMemoryStore(root / "restored.db"),
            FileEvidenceStore(root / "restored-evidence"),
            load_schema(),
        )
        restored.snapshot_import(snapshot)
        unknown = (
            MemoryAPI(restored).analysis_read({"observation_id": private["id"]}).result
        )
        assert unknown["observation"]["freshness"] == "unknown"
        return {
            "new_ticket_requires_join": True,
            "new_edges": 1,
            "atomic_type_rollback": True,
            "local_text_search_hits": 1,
            "private_capture_blocked_for_public_use": True,
            "snapshot_restored_freshness": "unknown",
        }
