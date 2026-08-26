from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from analytical_memory.api import MemoryAPI
from analytical_memory.application import MemoryApplication
from analytical_memory.configuration import (
    build_application,
    environment_database,
    environment_evidence_root,
)
from analytical_memory.errors import MemoryErrorBase
from analytical_memory.schema_compiler import (
    compile_schema,
    schema_is_current,
    write_schema,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory")
    parser.add_argument(
        "--database",
        type=Path,
        default=environment_database(),
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=environment_evidence_root(),
    )
    parser.add_argument("--schema", type=Path)
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("init")
    subcommands.add_parser("status")
    subcommands.add_parser("validate")
    subcommands.add_parser("capabilities")

    ingest = subcommands.add_parser("ingest")
    ingest_commands = ingest.add_subparsers(dest="ingest_command", required=True)
    for name in ("preview", "apply"):
        command = ingest_commands.add_parser(name)
        command.add_argument("batch", type=Path)

    query = subcommands.add_parser("query")
    query.add_argument(
        "query_name", choices=("current-facts", "current-slots", "current-metric")
    )
    query.add_argument("--definition-version")
    query.add_argument("--dimensions", default="{}")

    traverse = subcommands.add_parser("traverse")
    traverse.add_argument("start_node_id")
    traverse.add_argument("--relation-type", action="append", dest="relation_types")
    traverse.add_argument(
        "--direction", choices=("outbound", "inbound", "both"), default="outbound"
    )
    traverse.add_argument("--max-depth", type=int, default=3)
    traverse.add_argument("--limit", type=int, default=100)
    traverse.add_argument("--state", action="append", dest="states")

    search = subcommands.add_parser("search")
    search.add_argument("text")
    search.add_argument("--limit", type=int, default=20)

    explain = subcommands.add_parser("explain")
    explain.add_argument("record_id")
    explain.add_argument(
        "--kind",
        choices=("node_attribute", "relation", "metric"),
        default="node_attribute",
    )

    schema = subcommands.add_parser("schema")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    schema_commands.add_parser("show")
    compile_command = schema_commands.add_parser("compile")
    compile_command.add_argument("--check", action="store_true")
    return parser


def _application(arguments: argparse.Namespace) -> MemoryApplication:
    return build_application(
        database=arguments.database,
        evidence_root=arguments.evidence_root,
        schema_path=arguments.schema,
    )


def _execute(arguments: argparse.Namespace) -> dict[str, Any]:
    application = _application(arguments)
    api = MemoryAPI(application)
    if arguments.command == "init":
        return application.initialize()
    if arguments.command == "status":
        return application.status()
    if arguments.command == "validate":
        return application.validate()
    if arguments.command == "capabilities":
        return application.capabilities()
    if arguments.command == "ingest":
        if arguments.ingest_command == "preview":
            return api.ingestion_preview(arguments.batch).model_dump(mode="json")
        return api.ingestion_apply(arguments.batch).model_dump(mode="json")
    if arguments.command == "query":
        if arguments.query_name == "current-facts":
            return api.query_current_facts().model_dump(mode="json")
        if arguments.query_name == "current-slots":
            return api.query_current_slots().model_dump(mode="json")
        if arguments.definition_version is None:
            raise ValueError("--definition-version is required for current-metric")
        dimensions = json.loads(arguments.dimensions)
        if not isinstance(dimensions, dict):
            raise ValueError("--dimensions must be a JSON object")
        return api.query_current_metric(
            arguments.definition_version, dimensions
        ).model_dump(mode="json")
    if arguments.command == "traverse":
        return api.traverse_relations(
            arguments.start_node_id,
            relation_types=arguments.relation_types,
            direction=arguments.direction,
            max_depth=arguments.max_depth,
            limit=arguments.limit,
            states=arguments.states,
        ).model_dump(mode="json")
    if arguments.command == "search":
        return api.search_text(arguments.text, arguments.limit).model_dump(mode="json")
    if arguments.command == "explain":
        if arguments.kind == "relation":
            return api.explain_relation(arguments.record_id).model_dump(mode="json")
        if arguments.kind == "metric":
            return api.explain_metric(arguments.record_id).model_dump(mode="json")
        return api.explain(arguments.record_id).model_dump(mode="json")
    if arguments.command == "schema":
        if arguments.schema_command == "show":
            return application.schema.document
        if arguments.check:
            compiled = compile_schema()
            return {
                "current": schema_is_current(),
                "schema_fingerprint": compiled["schema_fingerprint"],
            }
        compiled = write_schema()
        return {
            "current": True,
            "schema_fingerprint": compiled["schema_fingerprint"],
            "written": True,
        }
    raise AssertionError(f"unsupported command: {arguments.command}")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = _execute(arguments)
    except (MemoryErrorBase, ValueError, OSError) as exc:
        json.dump(
            {"error": type(exc).__name__, "message": str(exc)},
            sys.stderr,
            ensure_ascii=False,
            sort_keys=True,
        )
        sys.stderr.write("\n")
        return 2
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    if arguments.command == "validate" and not result["ok"]:
        return 1
    if (
        arguments.command == "schema"
        and arguments.schema_command == "compile"
        and not result["current"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
