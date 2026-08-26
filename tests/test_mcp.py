from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters
from mcp.types import TextResourceContents

from analytical_memory.api import MemoryAPI
from analytical_memory.cli import main
from analytical_memory.mcp_server import create_mcp_server

from .conftest import REPOSITORY_ROOT, ApplicationFixture


def _tool_json(result: Any) -> dict[str, Any]:
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def _cli_json(capsys: Any, arguments: list[str]) -> dict[str, Any]:
    assert main(arguments) == 0
    value = json.loads(capsys.readouterr().out)
    assert isinstance(value, dict)
    return value


@pytest.mark.anyio
async def test_discovery_and_tools_match_cli_contracts(
    application_fixture: ApplicationFixture,
    tmp_path: Path,
    capsys: Any,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    server = create_mcp_server(fixture.application)
    api = MemoryAPI(fixture.application)

    async with Client(server, raise_exceptions=True) as client:
        resources = await client.list_resources()
        assert {str(item.uri) for item in resources.resources} == {
            "memory://capabilities/current",
            "memory://schema/current",
            "memory://schema/queries",
        }
        templates = await client.list_resource_templates()
        assert {item.uri_template for item in templates.resource_templates} == {
            "memory://schema/ontology/{namespace}"
        }

        schema_resource = await client.read_resource("memory://schema/current")
        assert isinstance(schema_resource.contents[0], TextResourceContents)
        schema = json.loads(schema_resource.contents[0].text)
        assert schema["schema_fingerprint"] == fixture.schema.fingerprint
        assert "NodeAttribute" in schema["record_types"]

        capabilities_resource = await client.read_resource(
            "memory://capabilities/current"
        )
        assert isinstance(capabilities_resource.contents[0], TextResourceContents)
        capabilities = json.loads(capabilities_resource.contents[0].text)
        assert capabilities["saved_queries"] == [
            "current-facts",
            "current-metric",
            "current-slots",
            "search-text",
            "traverse-relations",
        ]
        assert capabilities["limits"]["returned_query_items"] == 1_000
        assert capabilities["transports"]["stdio_mcp"]["enabled"] is True

        tools = await client.list_tools()
        tools_by_name = {tool.name: tool for tool in tools.tools}
        assert set(tools_by_name) == {
            "memory_explain",
            "memory_explain_metric",
            "memory_explain_relation",
            "memory_ingest_apply",
            "memory_ingest_preview",
            "memory_query_current_facts",
            "memory_query_current_metric",
            "memory_query_current_slots",
            "memory_search_text",
            "memory_traverse_relations",
        }
        assert tools_by_name["memory_ingest_preview"].input_schema["required"] == [
            "batch_path"
        ]
        explanation_schema = tools_by_name["memory_explain"].output_schema
        assert explanation_schema is not None
        assert "properties" in explanation_schema
        assert tools_by_name["memory_ingest_apply"].annotations is not None
        assert tools_by_name["memory_ingest_apply"].annotations.read_only_hint is False
        assert tools_by_name["memory_explain"].annotations is not None
        assert tools_by_name["memory_explain"].annotations.read_only_hint is True

        preview = _tool_json(
            await client.call_tool(
                "memory_ingest_preview", {"batch_path": str(fixture.batch_path)}
            )
        )
        assert preview == api.ingestion_preview(fixture.batch_path).model_dump(
            mode="json"
        )
        mcp_apply = _tool_json(
            await client.call_tool(
                "memory_ingest_apply", {"batch_path": str(fixture.batch_path)}
            )
        )
        mcp_query = _tool_json(await client.call_tool("memory_query_current_facts", {}))
        attribute_id = str(mcp_apply["result"]["attribute_ids"][0])
        mcp_explain = _tool_json(
            await client.call_tool("memory_explain", {"attribute_id": attribute_id})
        )

    cli_database = tmp_path / "cli-memory.db"
    cli_evidence = tmp_path / "cli-evidence"
    cli_shared = [
        "--database",
        str(cli_database),
        "--evidence-root",
        str(cli_evidence),
    ]
    _cli_json(capsys, [*cli_shared, "init"])
    cli_apply = _cli_json(
        capsys,
        [*cli_shared, "ingest", "apply", str(fixture.batch_path)],
    )
    cli_query = _cli_json(capsys, [*cli_shared, "query", "current-facts"])
    cli_explain = _cli_json(capsys, [*cli_shared, "explain", attribute_id])

    assert mcp_apply == cli_apply
    assert mcp_query == cli_query
    assert mcp_explain == cli_explain


@pytest.mark.anyio
async def test_mcp_rejects_stale_schema_with_refresh_pointer(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    document["schema_fingerprint"] = "0" * 64
    fixture.batch_path.write_text(json.dumps(document), encoding="utf-8")

    async with Client(create_mcp_server(fixture.application)) as client:
        result = await client.call_tool(
            "memory_ingest_apply", {"batch_path": str(fixture.batch_path)}
        )

    assert result.is_error is True
    text = " ".join(block.text for block in result.content if hasattr(block, "text"))
    assert fixture.schema.fingerprint in text
    assert "memory://schema/current" in text


@pytest.mark.anyio
async def test_local_stdio_server_is_discoverable(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "analytical_memory.mcp_server"],
        cwd=REPOSITORY_ROOT,
        env={
            "ANALYTICAL_MEMORY_DB": str(fixture.database),
            "ANALYTICAL_MEMORY_EVIDENCE_ROOT": str(fixture.evidence_store.root),
            "ANALYTICAL_MEMORY_SCHEMA": str(
                REPOSITORY_ROOT / "schema" / "current.json"
            ),
        },
    )

    async with Client(parameters) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        preview = await client.call_tool(
            "memory_ingest_preview", {"batch_path": str(fixture.batch_path)}
        )

    assert len(tools.tools) == 10
    assert len(resources.resources) == 3
    assert _tool_json(preview)["writes"] is False


@pytest.mark.anyio
async def test_milestone_two_tools_match_cli_shapes(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
    tmp_path: Path,
    capsys: Any,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    plan = fixture.application.plan(querying_batch_path)
    fixture.application.apply(querying_batch_path)

    async with Client(create_mcp_server(fixture.application)) as client:
        mcp_slots = _tool_json(await client.call_tool("memory_query_current_slots", {}))
        mcp_metric = _tool_json(
            await client.call_tool(
                "memory_query_current_metric",
                {
                    "definition_version": "example.count.v1",
                    "dimensions": {"scope": "all"},
                },
            )
        )
        mcp_traversal = _tool_json(
            await client.call_tool(
                "memory_traverse_relations",
                {"start_node_id": plan.nodes[0].id, "max_depth": 2},
            )
        )
        mcp_search = _tool_json(
            await client.call_tool(
                "memory_search_text", {"query": "connected", "limit": 10}
            )
        )
        mcp_relation_explanation = _tool_json(
            await client.call_tool(
                "memory_explain_relation", {"relation_id": plan.relations[0].id}
            )
        )
        mcp_metric_explanation = _tool_json(
            await client.call_tool(
                "memory_explain_metric", {"metric_id": plan.metrics[0].id}
            )
        )

    cli_shared = [
        "--database",
        str(tmp_path / "m2-cli.db"),
        "--evidence-root",
        str(tmp_path / "m2-cli-evidence"),
    ]
    _cli_json(capsys, [*cli_shared, "init"])
    _cli_json(
        capsys,
        [*cli_shared, "ingest", "apply", str(querying_batch_path)],
    )
    cli_slots = _cli_json(capsys, [*cli_shared, "query", "current-slots"])
    cli_metric = _cli_json(
        capsys,
        [
            *cli_shared,
            "query",
            "current-metric",
            "--definition-version",
            "example.count.v1",
            "--dimensions",
            '{"scope":"all"}',
        ],
    )
    cli_traversal = _cli_json(
        capsys,
        [*cli_shared, "traverse", plan.nodes[0].id, "--max-depth", "2"],
    )
    cli_search = _cli_json(
        capsys, [*cli_shared, "search", "connected", "--limit", "10"]
    )
    cli_relation_explanation = _cli_json(
        capsys,
        [
            *cli_shared,
            "explain",
            plan.relations[0].id,
            "--kind",
            "relation",
        ],
    )
    cli_metric_explanation = _cli_json(
        capsys,
        [*cli_shared, "explain", plan.metrics[0].id, "--kind", "metric"],
    )

    assert mcp_slots == cli_slots
    assert mcp_metric == cli_metric
    assert mcp_traversal == cli_traversal
    assert mcp_search == cli_search
    assert mcp_relation_explanation == cli_relation_explanation
    assert mcp_metric_explanation == cli_metric_explanation
