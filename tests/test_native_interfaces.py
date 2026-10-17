from __future__ import annotations

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
