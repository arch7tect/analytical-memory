from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from analytical_memory.api import MemoryAPI
from analytical_memory.application import MemoryApplication
from analytical_memory.canonical import strict_json_loads
from analytical_memory.configuration import (
    build_application,
    environment_backend,
    environment_database,
    environment_evidence_root,
    environment_memory_catalog,
    environment_postgres_schema,
    environment_postgres_url,
)
from analytical_memory.errors import MemoryErrorBase
from analytical_memory.memories import MemoryRouter, contextual_capabilities
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
    parser.add_argument(
        "--backend", choices=("sqlite", "postgresql"), default=environment_backend()
    )
    parser.add_argument("--postgres-url", default=environment_postgres_url())
    parser.add_argument("--postgres-schema", default=environment_postgres_schema())
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--memory")
    parser.add_argument("--catalog", type=Path, default=environment_memory_catalog())
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("init")
    subcommands.add_parser("status")
    subcommands.add_parser("validate")
    subcommands.add_parser("capabilities")

    memories = subcommands.add_parser("memories")
    memories_commands = memories.add_subparsers(dest="memories_command", required=True)
    memories_commands.add_parser("list")
    configure = memories_commands.add_parser("configure")
    configure.add_argument("action", choices=("create", "attach"))
    configure.add_argument("name")
    configure.add_argument(
        "--backend",
        dest="target_backend",
        choices=("sqlite", "postgresql"),
        required=True,
    )
    configure.add_argument("--database", dest="target_database", type=Path)
    configure.add_argument("--connection-env")
    configure.add_argument("--postgres-schema", dest="target_postgres_schema")
    configure.add_argument(
        "--evidence-root", dest="target_evidence_root", type=Path, required=True
    )

    jsonl_command = subcommands.add_parser("jsonl")
    jsonl_commands = jsonl_command.add_subparsers(dest="jsonl_command", required=True)
    jsonl_import = jsonl_commands.add_parser("import")
    jsonl_import.add_argument("source", type=Path)
    jsonl_import.add_argument("--entity-type", required=True)
    jsonl_import.add_argument("--key", required=True)
    jsonl_import.add_argument("--contract-fingerprint", required=True)

    ontology = subcommands.add_parser("ontology")
    ontology_commands = ontology.add_subparsers(dest="ontology_command", required=True)
    ontology_describe = ontology_commands.add_parser("describe")
    ontology_describe.add_argument("--namespace")
    ontology_declare = ontology_commands.add_parser("declare-entity")
    ontology_declare.add_argument("entity_type")
    ontology_declare.add_argument("--description")
    ontology_declare.add_argument(
        "--privacy", choices=("public", "private"), default="public"
    )
    ontology_declare.add_argument("--fields", default="{}")
    ontology_declare.add_argument("--contract-fingerprint", required=True)
    ontology_namespace = ontology_commands.add_parser("declare-namespace")
    ontology_namespace.add_argument("namespace")
    ontology_namespace.add_argument("--description", required=True)
    ontology_namespace.add_argument("--contract-fingerprint", required=True)

    query = subcommands.add_parser("query")
    query.add_argument(
        "query_name",
        choices=("current-metric", "execute"),
    )
    query.add_argument("--definition-version")
    query.add_argument("--dimensions", default="{}")
    query.add_argument("--document", type=Path)

    join = subcommands.add_parser("join")
    join_commands = join.add_subparsers(dest="join_command", required=True)
    join_materialize = join_commands.add_parser("materialize")
    join_materialize.add_argument("definition", type=Path)
    join_materialize.add_argument("--contract-fingerprint", required=True)
    join_materialize.add_argument("--idempotency-key")

    relation = subcommands.add_parser("relation")
    relation_commands = relation.add_subparsers(dest="relation_command", required=True)
    relation_deactivate = relation_commands.add_parser("deactivate")
    relation_deactivate.add_argument("relation_id")

    node = subcommands.add_parser("node")
    node_commands = node.add_subparsers(dest="node_command", required=True)
    node_delete = node_commands.add_parser("delete")
    node_delete.add_argument("node_id")

    attribute = subcommands.add_parser("attribute")
    attribute_commands = attribute.add_subparsers(
        dest="attribute_command", required=True
    )
    attribute_write = attribute_commands.add_parser("write-analysis")
    attribute_write.add_argument("node_id")
    attribute_write.add_argument("attribute_name")
    attribute_write.add_argument("--value", required=True)
    attribute_write.add_argument("--method", required=True)
    attribute_write.add_argument("--contract-fingerprint", required=True)

    metric = subcommands.add_parser("metric")
    metric_commands = metric.add_subparsers(dest="metric_command", required=True)
    metric_write = metric_commands.add_parser("write-analysis")
    metric_write.add_argument("definition_version")
    metric_write.add_argument("--value", required=True)
    metric_write.add_argument("--dimensions", default="{}")
    metric_write.add_argument("--method", required=True)
    metric_write.add_argument("--method-version", required=True)
    metric_write.add_argument("--coverage", default="{}")
    metric_write.add_argument("--incomplete", action="store_true")
    metric_write.add_argument("--unit")
    metric_write.add_argument("--numerator", type=float)
    metric_write.add_argument("--denominator", type=float)
    metric_write.add_argument(
        "--privacy", choices=("public", "private"), default="public"
    )
    metric_write.add_argument("--contract-fingerprint", required=True)

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
    search.add_argument("--semantic-profile")
    search.add_argument("--namespace")
    search.add_argument("--node-type")
    search.add_argument(
        "--privacy-ceiling",
        choices=("public",),
    )

    embedding = subcommands.add_parser("embedding")
    embedding_commands = embedding.add_subparsers(
        dest="embedding_command", required=True
    )
    embedding_create = embedding_commands.add_parser("create-profile")
    embedding_create.add_argument("attribute_name")
    embedding_create.add_argument(
        "--privacy-ceiling",
        choices=("public",),
    )
    embedding_status = embedding_commands.add_parser("status")
    embedding_status.add_argument("profile_id")
    embedding_rebuild = embedding_commands.add_parser("rebuild")
    embedding_rebuild.add_argument("profile_id")
    embedding_rebuild.add_argument("--reset", action="store_true")

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
    retention_release = retention_commands.add_parser("release")
    retention_release.add_argument("digest")
    retention_release.add_argument("--confirm", required=True)
    retention_release.add_argument("--reason", required=True)
    retention_release.add_argument("--released-at")
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

    transfer = subcommands.add_parser("transfer")
    transfer_commands = transfer.add_subparsers(dest="transfer_command", required=True)
    transfer_export = transfer_commands.add_parser("export")
    transfer_export.add_argument("destination", type=Path)
    transfer_export.add_argument("--created-at")
    transfer_import = transfer_commands.add_parser("import")
    transfer_import.add_argument("source", type=Path)

    sanitized_export = subcommands.add_parser("export")
    sanitized_export.add_argument("destination", type=Path)
    sanitized_export.add_argument(
        "--privacy-ceiling",
        choices=("public",),
        default="public",
    )
    sanitized_export.add_argument("--created-at")
    return parser


def _application(arguments: argparse.Namespace) -> MemoryApplication:
    default = build_application(
        database=arguments.database,
        evidence_root=arguments.evidence_root,
        schema_path=arguments.schema,
        backend=arguments.backend,
        postgres_url=arguments.postgres_url,
        postgres_schema=arguments.postgres_schema,
    )
    if arguments.memory is None or arguments.memory == "default":
        return default
    return MemoryRouter(default, arguments.catalog).resolve(arguments.memory)[1]


def _execute(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.command == "memories":
        default = build_application(
            database=arguments.database,
            evidence_root=arguments.evidence_root,
            schema_path=arguments.schema,
            backend=arguments.backend,
            postgres_url=arguments.postgres_url,
            postgres_schema=arguments.postgres_schema,
        )
        router = MemoryRouter(default, arguments.catalog)
        if arguments.memories_command == "list":
            return router.catalog()
        return router.configure(
            action=arguments.action,
            name=arguments.name,
            backend=arguments.target_backend,
            evidence_root=arguments.target_evidence_root,
            database=arguments.target_database,
            connection_env=arguments.connection_env,
            postgres_schema=arguments.target_postgres_schema,
        )
    application = _application(arguments)
    api = MemoryAPI(application)
    if arguments.command == "init":
        return application.initialize()
    if arguments.command == "status":
        result = application.status()
        result["runtime_fingerprint"] = contextual_capabilities(
            application, arguments.memory or "default"
        )["runtime_fingerprint"]
        return result
    if arguments.command == "validate":
        return application.validate()
    if arguments.command == "capabilities":
        return contextual_capabilities(application, arguments.memory or "default")
    if arguments.command == "jsonl":
        key = strict_json_loads(arguments.key)
        if not isinstance(key, list):
            raise ValueError("--key must be a JSON array")
        return api.jsonl_import(
            arguments.source,
            arguments.entity_type,
            key,
            arguments.contract_fingerprint,
        ).model_dump(mode="json")
    if arguments.command == "ontology":
        if arguments.ontology_command == "describe":
            return api.ontology(arguments.namespace).model_dump(mode="json")
        if arguments.ontology_command == "declare-namespace":
            return api.declare_namespace(
                arguments.namespace,
                arguments.description,
                arguments.contract_fingerprint,
            ).model_dump(mode="json")
        fields = strict_json_loads(arguments.fields)
        if not isinstance(fields, dict):
            raise ValueError("--fields must be a JSON object")
        return api.declare_entity(
            arguments.entity_type,
            arguments.privacy,
            fields,
            arguments.contract_fingerprint,
            arguments.description,
        ).model_dump(mode="json")
    if arguments.command == "query":
        if arguments.query_name == "execute":
            if arguments.document is None:
                raise ValueError("--document is required for query execute")
            document = strict_json_loads(arguments.document.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("query document must be a JSON object")
            return api.execute_query(document).model_dump(mode="json")
        if arguments.definition_version is None:
            raise ValueError("--definition-version is required for current-metric")
        dimensions = strict_json_loads(arguments.dimensions)
        if not isinstance(dimensions, dict):
            raise ValueError("--dimensions must be a JSON object")
        return api.query_current_metric(
            arguments.definition_version, dimensions
        ).model_dump(mode="json")
    if arguments.command == "join":
        definition = strict_json_loads(arguments.definition.read_text(encoding="utf-8"))
        if not isinstance(definition, dict):
            raise ValueError("join definition must be a JSON object")
        return api.materialize_join(
            str(definition["name"]),
            str(definition["relation"]),
            definition["from"],
            definition["to"],
            arguments.contract_fingerprint,
            arguments.idempotency_key,
            definition.get("description"),
        ).model_dump(mode="json")
    if arguments.command == "relation":
        return api.deactivate_relation(arguments.relation_id).model_dump(mode="json")
    if arguments.command == "node":
        return api.delete_node(arguments.node_id).model_dump(mode="json")
    if arguments.command == "attribute":
        return api.write_analytical_attribute(
            arguments.node_id,
            arguments.attribute_name,
            strict_json_loads(arguments.value),
            arguments.method,
            arguments.contract_fingerprint,
        ).model_dump(mode="json")
    if arguments.command == "metric":
        dimensions = strict_json_loads(arguments.dimensions)
        coverage = strict_json_loads(arguments.coverage)
        if not isinstance(dimensions, dict) or not isinstance(coverage, dict):
            raise ValueError("--dimensions and --coverage must be JSON objects")
        return api.write_analytical_metric(
            arguments.definition_version,
            strict_json_loads(arguments.value),
            dimensions,
            arguments.method,
            arguments.method_version,
            arguments.contract_fingerprint,
            coverage,
            not arguments.incomplete,
            arguments.unit,
            arguments.numerator,
            arguments.denominator,
            arguments.privacy,
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
        if arguments.semantic_profile is not None:
            return api.search_semantic(
                arguments.semantic_profile,
                arguments.text,
                namespace=arguments.namespace,
                node_type=arguments.node_type,
                privacy_ceiling=arguments.privacy_ceiling,
                limit=arguments.limit,
            ).model_dump(mode="json")
        return api.search_text(arguments.text, arguments.limit).model_dump(mode="json")
    if arguments.command == "embedding":
        if arguments.embedding_command == "create-profile":
            return api.embedding_profile_create(
                arguments.attribute_name, arguments.privacy_ceiling
            ).model_dump(mode="json")
        if arguments.embedding_command == "status":
            return api.embedding_profile_status(arguments.profile_id).model_dump(
                mode="json"
            )
        return api.embedding_rebuild(
            arguments.profile_id, reset=arguments.reset
        ).model_dump(mode="json")
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
        if arguments.retention_command == "release":
            return application.retention_release(
                arguments.digest,
                confirmation=arguments.confirm,
                reason=arguments.reason,
                released_at=arguments.released_at,
            )
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
    if arguments.command == "transfer":
        if arguments.transfer_command == "export":
            return application.transfer_export(
                arguments.destination, created_at=arguments.created_at
            )
        return application.transfer_import(arguments.source)
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
        memory = (
            arguments.name
            if arguments.command == "memories"
            and arguments.memories_command == "configure"
            else arguments.memory or "default"
        )
        if isinstance(exc, MemoryErrorBase):
            error = exc.envelope()
            error["details"] = {**error["details"], "memory": memory}
        else:
            error = {
                "error": type(exc).__name__,
                "memory": memory,
                "message": str(exc),
            }
        json.dump(
            error,
            sys.stderr,
            ensure_ascii=False,
            sort_keys=True,
        )
        sys.stderr.write("\n")
        return 2
    if arguments.command not in {"memories", "schema"}:
        result["memory"] = arguments.memory or "default"
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
