from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.types import TextResourceContents

from analytical_memory.configuration import build_application

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPOSITORY_ROOT / "examples" / "quickstart"


def structured(result: Any) -> dict[str, Any]:
    if result.is_error or not isinstance(result.structured_content, dict):
        raise RuntimeError("MCP tool failed or returned no structured content")
    nested = result.structured_content.get("result")
    return dict(nested) if isinstance(nested, dict) else result.structured_content


def error_document(result: Any) -> dict[str, Any]:
    if not result.is_error or not result.content:
        raise RuntimeError("MCP tool did not return the expected error")
    text = result.content[0].text
    return dict(json.loads(text[text.index("{") :]))


async def resource_document(client: Client, uri: str) -> dict[str, Any]:
    resource = await client.read_resource(uri)
    if not isinstance(resource.contents[0], TextResourceContents):
        raise RuntimeError(f"MCP resource {uri} is not textual")
    return dict(json.loads(resource.contents[0].text))


async def run_smoke() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="analytical-memory-mcp-") as directory:
        root = Path(directory)
        database = root / "memory.db"
        evidence_root = root / "evidence"
        build_application(
            database=database,
            evidence_root=evidence_root,
            schema_path=None,
        ).initialize()
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "analytical_memory.mcp_server"],
            cwd=REPOSITORY_ROOT,
            env={
                **os.environ,
                "ANALYTICAL_MEMORY_DB": str(database),
                "ANALYTICAL_MEMORY_EVIDENCE_ROOT": str(evidence_root),
                "ANALYTICAL_MEMORY_CATALOG": str(root / "memories.json"),
            },
        )
        async with Client(parameters) as client:
            guide = await resource_document(client, "memory://guide")
            if guide["selection"]["catalog"] != "memory://catalog":
                raise RuntimeError("guide does not link the catalog")
            fingerprint = str(
                (await resource_document(client, "memory://schema/current"))[
                    "schema_fingerprint"
                ]
            )
            query_contract = await resource_document(
                client, "memory://schema/query-ir/current"
            )
            if query_contract["query_ir_version"] != "1":
                raise RuntimeError("unexpected Query IR version")
            structured(
                await client.call_tool(
                    "memory_configure",
                    {
                        "action": "create",
                        "name": "research",
                        "backend": "sqlite",
                        "database": str(root / "research.db"),
                        "evidence_root": str(root / "research-evidence"),
                    },
                )
            )
            catalog = await resource_document(client, "memory://catalog")
            if catalog["memories"]["research"]["summary"] != (
                "memory://memories/research/summary"
            ):
                raise RuntimeError("catalog does not link the named summary")
            stale = await client.call_tool(
                "memory_ontology_manage",
                {
                    "action": "declare_namespace",
                    "memory": "research",
                    "payload": {
                        "contract_fingerprint": "stale",
                        "description": "Example data.",
                        "namespace": "example",
                    },
                },
            )
            stale_error = error_document(stale)
            if stale_error["code"] != "schema_changed":
                raise RuntimeError("unexpected stale-schema error")
            fingerprint = str(
                (await resource_document(client, "memory://schema/current"))[
                    "schema_fingerprint"
                ]
            )
            structured(
                await client.call_tool(
                    "memory_ontology_manage",
                    {
                        "action": "declare_namespace",
                        "memory": "research",
                        "payload": {
                            "contract_fingerprint": fingerprint,
                            "description": "Example data.",
                            "namespace": "example",
                        },
                    },
                )
            )
            structured(
                await client.call_tool(
                    "memory_ontology_manage",
                    {
                        "action": "declare_entity",
                        "memory": "research",
                        "payload": {
                            "contract_fingerprint": fingerprint,
                            "entity_type": "example.SessionMessage",
                            "fields": {
                                "message": {
                                    "searchable": True,
                                    "type": "string",
                                }
                            },
                        },
                    },
                )
            )
            replayed = False
            for filename, entity_type in (
                ("sessions.jsonl", "example.Session"),
                ("messages.jsonl", "example.SessionMessage"),
            ):
                imported = structured(
                    await client.call_tool(
                        "memory_ingest_manage",
                        {
                            "action": "jsonl_import",
                            "memory": "research",
                            "payload": {
                                "source_path": str(EXAMPLES / filename),
                                "entity_type": entity_type,
                                "key": [{"field": "id", "type": "string"}],
                                "contract_fingerprint": fingerprint,
                            },
                        },
                    )
                )
                if filename == "sessions.jsonl":
                    replayed = bool(
                        structured(
                            await client.call_tool(
                                "memory_ingest_manage",
                                {
                                    "action": "jsonl_import",
                                    "memory": "research",
                                    "payload": {
                                        "source_path": str(EXAMPLES / filename),
                                        "entity_type": entity_type,
                                        "key": [{"field": "id", "type": "string"}],
                                        "contract_fingerprint": fingerprint,
                                    },
                                },
                            )
                        )["replayed"]
                    )
                elif imported["replayed"]:
                    raise RuntimeError("first import unexpectedly replayed")
            definition = json.loads((EXAMPLES / "join.json").read_text())
            joined = structured(
                await client.call_tool(
                    "memory_relation_manage",
                    {
                        "action": "materialize",
                        "memory": "research",
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
                    {
                        "action": "execute",
                        "memory": "research",
                        "payload": {"document": query},
                    },
                )
            )
            searched = structured(
                await client.call_tool(
                    "memory_search_manage",
                    {
                        "action": "text",
                        "memory": "research",
                        "payload": {"query": "First"},
                    },
                )
            )
            if not searched["results"]:
                raise RuntimeError("text search returned no indexed match")
            summary = await resource_document(
                client, "memory://memories/research/summary"
            )
            if summary["content_status"] != "populated_current_graph":
                raise RuntimeError("summary did not report imported graph data")
        return {
            "catalog_memories": sorted(catalog["memories"]),
            "created_relations": joined["created_relations"],
            "import_replayed": replayed,
            "ok": True,
            "query_rows": len(queried["rows"]),
            "schema_recovery": stale_error["code"],
            "search_results": len(searched["results"]),
            "summary_status": summary["content_status"],
        }


def main() -> None:
    print(json.dumps(asyncio.run(run_smoke()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
