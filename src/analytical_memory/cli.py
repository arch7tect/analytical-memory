from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.application import MemoryApplication
from analytical_memory.errors import MemoryErrorBase
from analytical_memory.schema_contract import load_schema


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ.get("ANALYTICAL_MEMORY_DB", ".local/memory.db")),
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path(
            os.environ.get("ANALYTICAL_MEMORY_EVIDENCE_ROOT", ".local/evidence")
        ),
    )
    parser.add_argument("--schema", type=Path)
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("init")

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
    schema = load_schema(arguments.schema)
    return MemoryApplication(
        memory_store=SqliteMemoryStore(arguments.database),
        evidence_store=FileEvidenceStore(arguments.evidence_root),
        schema=schema,
    )


def _execute(arguments: argparse.Namespace) -> dict[str, Any]:
    application = _application(arguments)
    if arguments.command == "init":
        return application.initialize()
    if arguments.command == "ingest":
        if arguments.ingest_command == "preview":
            return application.preview(arguments.batch)
        return application.apply(arguments.batch)
    if arguments.command == "query":
        return application.current_facts()
    if arguments.command == "explain":
        return application.explain(arguments.record_id)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
