from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

from analytical_memory.configuration import build_application
from analytical_memory.schema_contract import default_schema_path, load_schema

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPOSITORY_ROOT / "examples" / "quickstart"
SCHEMA = default_schema_path()


def structured(result: Any) -> dict[str, Any]:
    if result.is_error or not isinstance(result.structured_content, dict):
        raise RuntimeError("MCP tool failed or returned no structured content")
    nested = result.structured_content.get("result")
    return dict(nested) if isinstance(nested, dict) else result.structured_content


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
        fingerprint = load_schema(SCHEMA).fingerprint
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "analytical_memory.mcp_server"],
            cwd=REPOSITORY_ROOT,
            env={
                **os.environ,
                "ANALYTICAL_MEMORY_DB": str(database),
                "ANALYTICAL_MEMORY_EVIDENCE_ROOT": str(evidence_root),
                "ANALYTICAL_MEMORY_SCHEMA": str(SCHEMA),
            },
        )
        async with Client(parameters) as client:
            for filename, entity_type in (
                ("sessions.jsonl", "example.Session"),
                ("messages.jsonl", "example.SessionMessage"),
            ):
                structured(
                    await client.call_tool(
                        "memory_ingest_manage",
                        {
                            "action": "jsonl_import",
                            "payload": {
                                "source_path": str(EXAMPLES / filename),
                                "entity_type": entity_type,
                                "key": [{"field": "id", "type": "string"}],
                                "contract_fingerprint": fingerprint,
                            },
                        },
                    )
                )
            definition = json.loads((EXAMPLES / "join.json").read_text())
            joined = structured(
                await client.call_tool(
                    "memory_relation_manage",
                    {
                        "action": "materialize",
                        "payload": {
                            "name": definition["name"],
                            "relation": definition["relation"],
                            "from": definition["from"],
                            "to": definition["to"],
                            "contract_fingerprint": fingerprint,
                        },
                    },
                )
            )
            query = json.loads((EXAMPLES / "query.json").read_text())
            queried = structured(
                await client.call_tool(
                    "memory_query_manage",
                    {"action": "execute", "payload": {"document": query}},
                )
            )
        return {
            "created_relations": joined["created_relations"],
            "ok": True,
            "query_rows": len(queried["rows"]),
        }


def main() -> None:
    print(json.dumps(asyncio.run(run_smoke()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
