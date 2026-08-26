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

    evidence = subcommands.add_parser("evidence")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_status = evidence_commands.add_parser("status")
    evidence_status.add_argument("digest")
    evidence_read = evidence_commands.add_parser("read")
    evidence_read.add_argument("digest")
    evidence_read.add_argument("--offset", type=int, default=0)
    evidence_read.add_argument("--limit", type=int, default=65536)
    evidence_verify = evidence_commands.add_parser("verify")
    evidence_verify.add_argument("digest")
    evidence_audit = evidence_commands.add_parser("audit")
    evidence_audit.add_argument("--limit", type=int, default=1000)

    retention = subcommands.add_parser("retention")
    retention_commands = retention.add_subparsers(
        dest="retention_command", required=True
    )
    retention_report = retention_commands.add_parser("report")
    retention_report.add_argument("--as-of")
    retention_plan = retention_commands.add_parser("plan")
    retention_plan.add_argument("output", type=Path)
    retention_plan.add_argument("--digest", action="append", dest="digests")
    retention_plan.add_argument("--created-at")
    retention_retire = retention_commands.add_parser("retire")
    retention_retire.add_argument("plan", type=Path)
    retention_retire.add_argument("--confirm", required=True)
    retention_retire.add_argument("--retired-at")

    snapshot = subcommands.add_parser("snapshot")
    snapshot_commands = snapshot.add_subparsers(dest="snapshot_command", required=True)
    snapshot_create = snapshot_commands.add_parser("create")
    snapshot_create.add_argument("destination", type=Path)
    snapshot_create.add_argument("--created-at")
    snapshot_verify = snapshot_commands.add_parser("verify")
    snapshot_verify.add_argument("source", type=Path)
    snapshot_import = snapshot_commands.add_parser("import")
    snapshot_import.add_argument("source", type=Path)

    sanitized_export = subcommands.add_parser("export")
    sanitized_export.add_argument("destination", type=Path)
    sanitized_export.add_argument(
        "--privacy-ceiling",
        choices=("public", "private", "restricted", "forbidden"),
        default="public",
    )
    sanitized_export.add_argument("--created-at")
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
    if arguments.command == "evidence":
        if arguments.evidence_command == "status":
            return api.evidence_status(arguments.digest).model_dump(mode="json")
        if arguments.evidence_command == "read":
            return api.evidence_read(
                arguments.digest, offset=arguments.offset, limit=arguments.limit
            ).model_dump(mode="json")
        if arguments.evidence_command == "verify":
            return api.evidence_verify(arguments.digest).model_dump(mode="json")
        return api.evidence_audit(arguments.limit).model_dump(mode="json")
    if arguments.command == "retention":
        if arguments.retention_command == "report":
            return application.retention_report(as_of=arguments.as_of)
        if arguments.retention_command == "plan":
            return application.retention_plan(
                arguments.output,
                digests=arguments.digests,
                created_at=arguments.created_at,
            )
        return application.retention_retire(
            arguments.plan,
            confirmation=arguments.confirm,
            retired_at=arguments.retired_at,
        )
    if arguments.command == "snapshot":
        if arguments.snapshot_command == "create":
            return application.snapshot_create(
                arguments.destination, created_at=arguments.created_at
            )
        if arguments.snapshot_command == "verify":
            return application.snapshot_verify(arguments.source)
        return application.snapshot_import(arguments.source)
    if arguments.command == "export":
        return application.sanitized_export(
            arguments.destination,
            privacy_ceiling=arguments.privacy_ceiling,
            created_at=arguments.created_at,
        )
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
