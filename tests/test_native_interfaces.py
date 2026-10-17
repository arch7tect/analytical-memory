from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.api import MemoryAPI
from analytical_memory.application import MemoryApplication
from analytical_memory.schema_contract import load_schema
from tests.test_native_analytics import populate


@pytest.mark.anyio
async def test_native_bundle_capture_and_detail_through_stdio(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    evidence = tmp_path / "evidence"
    app = MemoryApplication(
        SqliteMemoryStore(database), FileEvidenceStore(evidence), load_schema()
    )
    app.initialize()
    document = populate(MemoryAPI(app))
    environment = {
        **os.environ,
        "ANALYTICAL_MEMORY_BACKEND": "sqlite",
        "ANALYTICAL_MEMORY_DB": str(database),
        "ANALYTICAL_MEMORY_EVIDENCE_ROOT": str(evidence),
        "ANALYTICAL_MEMORY_CATALOG": str(tmp_path / "catalog.json"),
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "analytical_memory.mcp_server"],
        env=environment,
    )
    async with Client(parameters) as client:

        async def query(action: str, document: dict[str, Any]) -> dict[str, Any]:
            response = await client.call_tool(
                "memory_query_manage",
                {"action": action, "payload": {"document": document}},
            )
            assert not response.is_error, response.content
            assert response.structured_content is not None
            return dict(response.structured_content["result"]["result"])

        v1 = {
            "query_ir_version": "1",
            "match": {"nodes": [{"as": "o", "type": "shop.Order"}], "edges": []},
            "return": [{"field": "o.order_id"}, {"field": "o.amount_cents"}],
            "order_by": [{"field": "o.order_id", "direction": "asc"}],
            "limit": 3,
        }
        compact_call = await client.call_tool(
            "memory_query_manage", {"action": "execute", "payload": {"document": v1}}
        )
        full_call = await client.call_tool(
            "memory_query_manage",
            {
                "action": "execute",
                "payload": {"document": v1, "response_format": "full"},
            },
        )
        assert not compact_call.is_error and not full_call.is_error
        assert compact_call.structured_content and full_call.structured_content
        compact = compact_call.structured_content["result"]
        full = full_call.structured_content["result"]
        assert compact["response_format"] == "compact"
        assert compact["rows"][0]["bindings"] == full["rows"][0]["bindings"]
        assert compact["ordering"] == full["ordering"]
        assert len(json.dumps(compact)) < len(json.dumps(full)) / 2
        for small_row, full_row in zip(compact["rows"], full["rows"], strict=True):
            for small, large in zip(
                small_row["projections"], full_row["projections"], strict=True
            ):
                assert small["value"] == large["value"]
                assert small["record_id"] == large["record_id"]
                assert "source_id" not in small and large["source_id"]
        explanation = await client.call_tool(
            "memory_explain_manage",
            {
                "action": "attribute",
                "payload": {
                    "attribute_id": compact["rows"][0]["projections"][0]["record_id"]
                },
            },
        )
        assert not explanation.is_error
        bad_format = await client.call_tool(
            "memory_query_manage",
            {
                "action": "execute",
                "payload": {"document": v1, "response_format": "tiny"},
            },
        )
        assert bad_format.is_error
        analysed = await query("analysis_execute", document)
        assert analysed["coverage"]["attributed"] == 10
        direct = await query("execute", document["members"][0]["document"])
        assert direct["total_groups"] == 4
        response = await client.call_tool(
            "memory_ingest_manage",
            {
                "action": "analysis_capture",
                "payload": {
                    "document": {
                        "analysis": document,
                        "definition_version": "mcp-retail-1",
                        "expected_state": analysed["state"],
                    }
                },
            },
        )
        assert not response.is_error, response.content
        assert response.structured_content is not None
        saved = response.structured_content["result"]["result"]
        read = await query(
            "analysis_read", {"observation_id": saved["id"], "fresh_only": True}
        )
        assert read["verified"]
        status = await query(
            "analysis_read", {"observation_id": saved["id"], "view": "status"}
        )
        assert status["verified"] and "results" not in status
        assert status["observation"] == read["observation"]
        group = direct["groups"][0]
        detail = await query(
            "query_drill_down",
            {
                "observation_id": saved["id"],
                "query_name": "by_carrier_region",
                "group_key": group["key"],
                "measure": "affected_orders",
                "view": "provenance",
            },
        )
        assert detail["total_members"] == 3
        assert detail["rows"][0]["attributes"][0]["provenance"]["evidence_object"][
            "digest"
        ]
        request = {
            "observation_id": saved["id"],
            "query_name": "by_carrier_region",
            "group_key": group["key"],
            "measure": "affected_orders",
            "limit": 1,
        }
        compact_detail = await query("query_drill_down", request)
        full_detail_call = await client.call_tool(
            "memory_query_manage",
            {
                "action": "query_drill_down",
                "payload": {"document": request, "response_format": "full"},
            },
        )
        assert not full_detail_call.is_error and full_detail_call.structured_content
        full_detail = full_detail_call.structured_content["result"]["result"]
        assert compact_detail["response_format"] == "compact"
        assert {
            k: v
            for k, v in compact_detail.items()
            if k not in {"rows", "response_format"}
        } == {k: v for k, v in full_detail.items() if k != "rows"}
        assert compact_detail["total_members"] == 3 and compact_detail["truncated"]
        assert compact_detail["mode"] == "observation_time"
        assert (
            len(json.dumps(compact_detail["rows"]))
            < len(json.dumps(full_detail["rows"])) / 2
        )
        assert (
            compact_detail["rows"][0]["node"]["id"]
            == full_detail["rows"][0]["node"]["id"]
        )
        assert "source_id" not in compact_detail["rows"][0]["attributes"][0]
        assert compact_detail["rows"][0]["node"]["privacy_class"] == "public"
        assert compact_detail["rows"][0]["attributes"][0]["privacy_class"] == "public"
        from analytical_memory.retail_quickstart import EXAMPLES

        MemoryAPI(app).jsonl_import(
            EXAMPLES / "correction.jsonl",
            "shop.Ticket",
            [{"field": "ticket_id", "type": "string"}],
            app.schema.fingerprint,
        )
        historical = await query(
            "query_drill_down",
            {
                **request,
                "measure": "delivery_tickets",
                "limit": 100,
            },
        )
        live_request = {
            "query": document["members"][0]["document"],
            "group_key": group["key"],
            "measure": "delivery_tickets",
            "expected_state": analysed["state"],
        }
        stale = await client.call_tool(
            "memory_query_manage",
            {
                "action": "query_drill_down",
                "payload": {"document": live_request},
            },
        )
        assert stale.is_error
        current = await query(
            "query_drill_down",
            {
                **live_request,
                "expected_state": MemoryAPI(app).data_state().result,
            },
        )
        assert historical["total_members"] == 3 and current["total_members"] == 4
        assert historical["observation"]["freshness"] == "potentially_stale"
        assert historical["state"] == analysed["state"]
        assert current["state"] != historical["state"]
        public_stale = await client.call_tool(
            "memory_query_manage",
            {
                "action": "query_drill_down",
                "payload": {"document": {**request, "public": True}},
            },
        )
        assert public_stale.is_error
        bad = await client.call_tool(
            "memory_query_manage",
            {"action": "analysis_read", "payload": {"document": {"public": True}}},
        )
        assert bad.is_error


def test_named_quickstart_cli_preserves_data_and_refuses_second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from analytical_memory import quickstart
    from analytical_memory.memories import MemoryRouter

    app = MemoryApplication(
        SqliteMemoryStore(tmp_path / "default.db"),
        FileEvidenceStore(tmp_path / "default-evidence"),
        load_schema(),
    )
    catalog = tmp_path / "catalog.json"
    router = MemoryRouter(app, catalog)
    router.configure(
        action="create",
        name="retail",
        backend="sqlite",
        database=tmp_path / "retail.db",
        evidence_root=tmp_path / "retail-evidence",
    )
    monkeypatch.setenv("ANALYTICAL_MEMORY_CATALOG", str(catalog))
    monkeypatch.setenv("ANALYTICAL_MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("ANALYTICAL_MEMORY_DB", str(tmp_path / "default.db"))
    monkeypatch.setenv(
        "ANALYTICAL_MEMORY_EVIDENCE_ROOT", str(tmp_path / "default-evidence")
    )
    monkeypatch.setattr(
        sys, "argv", ["memory-quickstart", "--memory", "retail", "--json"]
    )
    quickstart.main()
    _, stored = router.resolve("retail")
    assert stored.memory_store.lifecycle_state()["nodes"] == 28
    with pytest.raises(ValueError, match="dedicated empty memory"):
        quickstart.main()
    assert stored.memory_store.lifecycle_state()["nodes"] == 28


def test_public_and_packaged_retail_fixtures_match() -> None:
    from analytical_memory.retail_quickstart import EXAMPLES

    public = Path(__file__).resolve().parents[1] / "examples" / "retail"
    assert {p.name for p in public.iterdir()} == {p.name for p in EXAMPLES.iterdir()}
    assert all(
        path.read_bytes() == (EXAMPLES / path.name).read_bytes()
        for path in public.iterdir()
    )
