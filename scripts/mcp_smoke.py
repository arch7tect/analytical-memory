from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.types import TextResourceContents

from analytical_memory.configuration import build_application

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BATCH = REPOSITORY_ROOT / "examples" / "quickstart" / "batch.json"
SCHEMA = REPOSITORY_ROOT / "schema" / "current.json"


def structured(result: Any) -> dict[str, Any]:
    if result.is_error or not isinstance(result.structured_content, dict):
        raise RuntimeError("MCP tool failed or returned no structured content")
    return result.structured_content


async def run_smoke() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="analytical-memory-mcp-") as directory:
        root = Path(directory)
        database = root / "memory.db"
        evidence_root = root / "evidence"
        build_application(
            database=database,
            evidence_root=evidence_root,
            schema_path=SCHEMA,
        ).initialize()
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "analytical_memory.mcp_server"],
            cwd=REPOSITORY_ROOT,
            env={
                "ANALYTICAL_MEMORY_DB": str(database),
                "ANALYTICAL_MEMORY_EVIDENCE_ROOT": str(evidence_root),
                "ANALYTICAL_MEMORY_SCHEMA": str(SCHEMA),
            },
        )
        async with Client(parameters) as client:
            resources = await client.list_resources()
            tools = await client.list_tools()
            schema_result = await client.read_resource("memory://schema/current")
            capabilities_result = await client.read_resource(
                "memory://capabilities/current"
            )
            preview = structured(
                await client.call_tool(
                    "memory_ingest_preview", {"batch_path": str(BATCH)}
                )
            )
            applied = structured(
                await client.call_tool(
                    "memory_ingest_apply", {"batch_path": str(BATCH)}
                )
            )
            digest = str(applied["result"]["evidence_digest"])
            evidence_status = structured(
                await client.call_tool("memory_evidence_status", {"digest": digest})
            )
            evidence_read = structured(
                await client.call_tool(
                    "memory_evidence_read",
                    {"digest": digest, "offset": 0, "limit": 8},
                )
            )
            current = structured(
                await client.call_tool("memory_query_current_facts", {})
            )
            attribute_id = str(applied["result"]["attribute_ids"][0])
            explanation = structured(
                await client.call_tool("memory_explain", {"attribute_id": attribute_id})
            )

        if not isinstance(schema_result.contents[0], TextResourceContents):
            raise RuntimeError("schema resource is not text")
        if not isinstance(capabilities_result.contents[0], TextResourceContents):
            raise RuntimeError("capabilities resource is not text")
        schema = json.loads(schema_result.contents[0].text)
        capabilities = json.loads(capabilities_result.contents[0].text)
        states = sorted(str(item["state"]) for item in current["results"])
        verification = explanation["assertions"][0]["evidence"][0]["status"][
            "verification"
        ]
        if preview["writes"] is not False:
            raise RuntimeError("MCP preview unexpectedly wrote state")
        if verification != "verified":
            raise RuntimeError("MCP explanation did not verify evidence")
        if evidence_status["verification"] != "verified":
            raise RuntimeError("MCP evidence status did not verify the object")
        if evidence_read["byte_count"] != 8:
            raise RuntimeError("MCP bounded evidence read returned the wrong size")
        if "NodeAttribute" not in schema["record_types"]:
            raise RuntimeError("schema discovery omitted implemented record types")
        if "current-facts" not in capabilities["saved_queries"]:
            raise RuntimeError("capabilities discovery omitted the saved query")
        return {
            "discovered_resources": len(resources.resources),
            "discovered_tools": len(tools.tools),
            "evidence_verification": verification,
            "fact_states": states,
            "ok": True,
            "saved_queries": capabilities["saved_queries"],
        }


def main() -> None:
    print(json.dumps(asyncio.run(run_smoke()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
