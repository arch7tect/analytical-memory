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
    query.add_argument("query_name", choices=("current-facts",))

    explain = subcommands.add_parser("explain")
    explain.add_argument("record_id")
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
        return api.query_current_facts().model_dump(mode="json")
    if arguments.command == "explain":
        return api.explain(arguments.record_id).model_dump(mode="json")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
