from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from analytical_memory.adapters.sql_dialect import SqlDialect, SqliteDialect
from analytical_memory.canonical import (
    canonical_json,
    sha256_bytes,
    sha256_json,
    stable_uuid,
)
from analytical_memory.domain import (
    AnalyticalAttributeRequest,
    AnalyticalMetricRequest,
    EmbeddingProfileRecord,
    EmbeddingRecord,
    EntityDeclaration,
    ImportEvidence,
    JoinRequest,
    JsonlImportRequest,
    JsonlScan,
    MemoryStoreStatus,
    QueryPlan,
    StoredBatch,
)
from analytical_memory.errors import (
    AmbiguousTargetError,
    BatchValidationError,
    ImportValidationError,
    JoinConflictError,
    OntologyConflictError,
    QueryValidationError,
    RecordNotFoundError,
    RetentionBlockedError,
    SnapshotError,
    StoreNotInitializedError,
)
from analytical_memory.jsonl import iter_jsonl, json_type, split_entity_type
from analytical_memory.migrations import (
    default_migrations_directory,
    load_migration_manifest,
    migrate_sqlite,
)
from analytical_memory.ontology import ontology_document
from analytical_memory.ports import MemoryStore

SNAPSHOT_TABLES = (
    "ingestion_batch",
    "source",
    "analytical_run",
    "node",
    "node_attribute",
    "relation",
    "metric",
    "entity_declaration",
    "observed_field",
    "ontology_declaration",
    "evidence_object",
    "evidence_acquisition",
    "evidence_derivation",
    "evidence_fragment",
    "search_document",
    "evidence_location",
    "evidence_verification",
    "evidence_retirement",
)
SNAPSHOT_ORDER = {"observed_field": "entity_type, field_name"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sort_values(value: Any) -> tuple[str | None, str | None, float | None]:
    if isinstance(value, str):
        return value.casefold(), value, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None, None, float(value)
    return None, None, None


def _backfill_attribute_type(
    connection: sqlite3.Connection,
    entity_type: str,
    attribute_name: str,
    resolved_type: str,
) -> None:
    if resolved_type == "unresolved":
        return
    namespace, node_type = split_entity_type(entity_type)
    connection.execute(
        "UPDATE node_attribute SET json_type = ? "
        "WHERE attribute_name = ? AND json_type = 'unresolved' "
        "AND node_id IN (SELECT id FROM node WHERE namespace = ? AND type = ?)",
        (resolved_type, attribute_name, namespace, node_type),
    )


class SqlMemoryStore(MemoryStore):
    def __init__(
        self, database: Path, migrations_directory: Path | None = None
    ) -> None:
        self.database = database
        self.migrations_directory = (
            migrations_directory or default_migrations_directory()
        )
        self.dialect: SqlDialect = SqliteDialect()

    def _connect(self, *, require_initialized: bool = True) -> sqlite3.Connection:
        if require_initialized and not self.database.is_file():
            raise StoreNotInitializedError("memory store is not initialized")
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect(require_initialized=False) as connection:
            migrate_sqlite(connection, self.migrations_directory)
            rows = connection.execute(
                "SELECT id, value_json FROM node_attribute "
                "WHERE (json_type = 'string' AND "
                "(sort_text_folded IS NULL OR sort_text_exact IS NULL)) "
                "OR (json_type = 'number' AND sort_number IS NULL)"
            ).fetchall()
            with connection:
                for row in rows:
                    folded, exact, number = _sort_values(
                        json.loads(str(row["value_json"]))
                    )
                    connection.execute(
                        "UPDATE node_attribute SET sort_text_folded = ?, "
                        "sort_text_exact = ?, sort_number = ? WHERE id = ?",
                        (folded, exact, number, row["id"]),
                    )

    @contextmanager
    def _write_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        except self.dialect.integrity_errors as exc:
            raise BatchValidationError(
                f"batch violates storage constraints: {exc}"
            ) from exc
        finally:
            connection.close()

    def get_batch(self, idempotency_key: str) -> StoredBatch | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT input_hash, result_json FROM ingestion_batch "
                "WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        result = json.loads(str(row["result_json"]))
        if not isinstance(result, dict):
            raise ValueError("stored batch result must be an object")
        return StoredBatch(input_hash=str(row["input_hash"]), result=result)

    @staticmethod
    def _declaration_fields(raw: str | None) -> dict[str, dict[str, Any]]:
        if raw is None:
            return {}
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("stored declaration fields must be an object")
        return value

    @staticmethod
    def _ontology_snapshot_connection(
        connection: sqlite3.Connection, namespace: str | None = None
    ) -> dict[str, Any]:
        declarations = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM entity_declaration "
                "WHERE (? IS NULL OR substr(entity_type, 1, length(?) + 1) = ? || '.') "
                "ORDER BY entity_type",
                (namespace, namespace, namespace),
            ).fetchall()
        ]
        fields = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM observed_field "
                "WHERE (? IS NULL OR substr(entity_type, 1, length(?) + 1) = ? || '.') "
                "ORDER BY entity_type, field_name",
                (namespace, namespace, namespace),
            ).fetchall()
        ]
        joins: list[dict[str, Any]] = []
        for row in connection.execute(
            "SELECT * FROM ontology_declaration "
            "WHERE (? IS NULL "
            "OR substr(from_entity, 1, length(?) + 1) = ? || '.' "
            "OR substr(to_entity, 1, length(?) + 1) = ? || '.') "
            "ORDER BY name",
            (namespace, namespace, namespace, namespace, namespace),
        ).fetchall():
            item = dict(row)
            item["from_fields"] = json.loads(str(row["from_fields_json"]))
            item["to_fields"] = json.loads(str(row["to_fields_json"]))
            counts = connection.execute(
                "SELECT SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) "
                "AS active_count, "
                "SUM(CASE WHEN active = 0 THEN 1 ELSE 0 END) AS inactive_count "
                "FROM relation "
                "WHERE logical_key = ? AND type = ?",
                (row["name"], row["relation_type"]),
            ).fetchone()
            item["active_edge_count"] = int(counts[0] or 0)
            item["inactive_edge_count"] = int(counts[1] or 0)
            joins.append(item)
        statistics = {
            "nodes": int(
                connection.execute(
                    "SELECT COUNT(*) FROM node WHERE (? IS NULL OR namespace = ?)",
                    (namespace, namespace),
                ).fetchone()[0]
            ),
            "attributes": int(
                connection.execute(
                    "SELECT COUNT(*) FROM node_attribute AS attribute "
                    "JOIN node ON node.id = attribute.node_id "
                    "WHERE (? IS NULL OR node.namespace = ?)",
                    (namespace, namespace),
                ).fetchone()[0]
            ),
            "active_relations": int(
                connection.execute(
                    "SELECT COUNT(*) FROM relation "
                    "JOIN node AS source ON source.id = relation.source_node_id "
                    "JOIN node AS target ON target.id = relation.target_node_id "
                    "WHERE relation.active = 1 AND "
                    "(? IS NULL OR source.namespace = ? OR target.namespace = ?)",
                    (namespace, namespace, namespace),
                ).fetchone()[0]
            ),
        }
        return ontology_document(declarations, fields, joins, statistics)

    def ontology_snapshot(self, namespace: str | None = None) -> dict[str, Any]:
        with self._connect() as connection:
            return self._ontology_snapshot_connection(connection, namespace)

    def put_entity_declaration(
        self,
        declaration: EntityDeclaration,
        contract_fingerprint: str,
        evidence: ImportEvidence,
    ) -> dict[str, Any]:
        split_entity_type(declaration.entity_type)
        if declaration.privacy not in {"public", "private"}:
            raise ImportValidationError("privacy must be public or private")
        names = [field.name for field in declaration.fields]
        if len(names) != len(set(names)):
            raise ImportValidationError("declared field names must be unique")
        fields: dict[str, dict[str, Any]] = {}
        for field in declaration.fields:
            if not field.name:
                raise ImportValidationError("declared field name must not be empty")
            declared_type = field.type
            if declared_type == "integer":
                declared_type = "number"
            if declared_type not in {
                None,
                "string",
                "number",
                "boolean",
                "object",
                "array",
            }:
                raise ImportValidationError(
                    f"unsupported declared type for {field.name}: {field.type}"
                )
            privacy = field.privacy or declaration.privacy
            if privacy not in {"public", "private"}:
                raise ImportValidationError("privacy must be public or private")
            fields[field.name] = {
                "nullable": field.nullable,
                "privacy": privacy,
                "required": field.required,
                "searchable": field.searchable,
                "type": declared_type,
            }
        fields_json = canonical_json(fields)
        declaration_hash = sha256_json(
            {
                "entity_type": declaration.entity_type,
                "fields": fields,
                "privacy": declaration.privacy,
            }
        )
        recorded_at = _now()
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source_id = stable_uuid(
                "source", "entity-declaration", evidence.object.digest
            )
            run_id = stable_uuid(
                "analytical_run", "entity-declaration", evidence.object.digest
            )
            connection.execute(
                "INSERT INTO source "
                "(id, natural_key, kind, locator, privacy_class, recorded_at) "
                "VALUES (?, ?, 'entity-declaration', ?, ?, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (
                    source_id,
                    f"entity-declaration:{evidence.object.digest}",
                    f"evidence:sha256:{evidence.object.digest}",
                    evidence.object.privacy_class,
                    recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_object "
                "(id, digest, byte_size, media_type, privacy_class, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (
                    evidence.object.id,
                    evidence.object.digest,
                    evidence.object.byte_size,
                    evidence.object.media_type,
                    evidence.object.privacy_class,
                    evidence.object.recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_fragment "
                "(id, evidence_object_id, locator_kind, locator_json, extractor_id, "
                "extractor_version, byte_size, digest, privacy_class, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (
                    evidence.fragment.id,
                    evidence.fragment.evidence_object_id,
                    evidence.fragment.locator_kind,
                    evidence.fragment.locator_json,
                    evidence.fragment.extractor_id,
                    evidence.fragment.extractor_version,
                    evidence.fragment.byte_size,
                    evidence.fragment.digest,
                    evidence.fragment.privacy_class,
                    evidence.fragment.recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO analytical_run "
                "(id, idempotency_key, batch_id, source_id, method, recorded_at) "
                "VALUES (?, ?, NULL, ?, 'entity-declaration-v1', ?) "
                "ON CONFLICT(id) DO NOTHING",
                (
                    run_id,
                    f"entity-declaration:{evidence.object.digest}",
                    source_id,
                    recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_acquisition "
                "(id, evidence_object_id, source_id, run_id, privacy_class, "
                "retention_required, retain_until, method, review_status, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, 1, NULL, 'entity-declaration-v1', "
                "'unreviewed', ?) ON CONFLICT(id) DO NOTHING",
                (
                    stable_uuid("evidence_acquisition", evidence.object.id, run_id),
                    evidence.object.id,
                    source_id,
                    run_id,
                    evidence.object.privacy_class,
                    recorded_at,
                ),
            )
            existing = connection.execute(
                "SELECT * FROM entity_declaration WHERE entity_type = ?",
                (declaration.entity_type,),
            ).fetchone()
            if (
                existing is not None
                and str(existing["privacy_class"]) == "private"
                and declaration.privacy == "public"
            ):
                raise OntologyConflictError("entity privacy cannot be loosened")
            observed_rows = connection.execute(
                "SELECT * FROM observed_field WHERE entity_type = ?",
                (declaration.entity_type,),
            ).fetchall()
            observed = {str(row["field_name"]): row for row in observed_rows}
            for name, specification in fields.items():
                row = observed.get(name)
                if row is None:
                    continue
                known_type = str(row["json_type"])
                requested_type = specification["type"]
                if (
                    requested_type is not None
                    and known_type != "unresolved"
                    and requested_type != known_type
                ):
                    raise OntologyConflictError(
                        f"field {name!r} already has type {known_type}"
                    )
                if (
                    str(row["privacy_class"]) == "private"
                    and specification["privacy"] == "public"
                ):
                    raise OntologyConflictError(
                        f"field {name!r} privacy cannot be loosened"
                    )
                if not specification["nullable"]:
                    null_row = connection.execute(
                        "SELECT 1 FROM node_attribute AS attribute "
                        "JOIN node ON node.id = attribute.node_id "
                        "WHERE node.namespace || '.' || node.type = ? "
                        "AND attribute.attribute_name = ? "
                        "AND attribute.value_json = 'null' LIMIT 1",
                        (declaration.entity_type, name),
                    ).fetchone()
                    if null_row is not None:
                        raise OntologyConflictError(
                            f"field {name!r} has current null values"
                        )
            if existing is not None:
                connection.execute(
                    "UPDATE entity_declaration SET privacy_class = ?, fields_json = ?, "
                    "declaration_hash = ?, source_id = ?, fragment_id = ?, "
                    "recorded_at = ? WHERE entity_type = ?",
                    (
                        declaration.privacy,
                        fields_json,
                        declaration_hash,
                        source_id,
                        evidence.fragment.id,
                        recorded_at,
                        declaration.entity_type,
                    ),
                )
            else:
                connection.execute(
                    "INSERT INTO entity_declaration "
                    "(entity_type, privacy_class, fields_json, declaration_hash, "
                    "source_id, fragment_id, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        declaration.entity_type,
                        declaration.privacy,
                        fields_json,
                        declaration_hash,
                        source_id,
                        evidence.fragment.id,
                        recorded_at,
                    ),
                )
            for name, specification in fields.items():
                requested_type = specification["type"] or "unresolved"
                connection.execute(
                    "INSERT INTO observed_field "
                    "(entity_type, field_name, json_type, privacy_class, required, "
                    "nullable, searchable, declared, first_batch_id, last_batch_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL, NULL) "
                    "ON CONFLICT(entity_type, field_name) DO UPDATE SET "
                    "json_type = CASE WHEN observed_field.json_type = 'unresolved' "
                    "THEN excluded.json_type ELSE observed_field.json_type END, "
                    "privacy_class = CASE WHEN "
                    "observed_field.privacy_class = 'private' "
                    "THEN 'private' ELSE excluded.privacy_class END, "
                    "required = excluded.required, nullable = excluded.nullable, "
                    "searchable = excluded.searchable, declared = 1",
                    (
                        declaration.entity_type,
                        name,
                        requested_type,
                        specification["privacy"],
                        int(specification["required"]),
                        int(specification["nullable"]),
                        int(specification["searchable"]),
                    ),
                )
                _backfill_attribute_type(
                    connection,
                    declaration.entity_type,
                    name,
                    requested_type,
                )
            if declaration.privacy == "private":
                namespace, node_type = split_entity_type(declaration.entity_type)
                connection.execute(
                    "UPDATE node SET privacy_class = 'private', updated_at = ? "
                    "WHERE namespace = ? AND type = ?",
                    (recorded_at, namespace, node_type),
                )
                connection.execute(
                    "UPDATE node_attribute SET privacy_class = 'private', "
                    "updated_at = ? WHERE node_id IN "
                    "(SELECT id FROM node WHERE namespace = ? AND type = ?)",
                    (recorded_at, namespace, node_type),
                )
            for name, specification in fields.items():
                if specification["privacy"] == "private":
                    connection.execute(
                        "UPDATE node_attribute SET privacy_class = 'private', "
                        "updated_at = ? "
                        "WHERE attribute_name = ? AND node_id IN "
                        "(SELECT id FROM node WHERE namespace || '.' || type = ?)",
                        (recorded_at, name, declaration.entity_type),
                    )
            connection.execute(
                "UPDATE search_document SET privacy_class = 'private' "
                "WHERE target_id IN "
                "(SELECT id FROM node_attribute WHERE privacy_class = 'private')"
            )
            connection.execute(
                "UPDATE evidence_fragment SET privacy_class = 'private' "
                "WHERE id IN (SELECT fragment_id FROM node_attribute "
                "WHERE privacy_class = 'private' AND fragment_id IS NOT NULL)"
            )
            connection.execute(
                "UPDATE evidence_object SET privacy_class = 'private' "
                "WHERE id IN (SELECT evidence_object_id FROM evidence_fragment "
                "WHERE privacy_class = 'private')"
            )
            connection.execute(
                "UPDATE evidence_acquisition SET privacy_class = 'private' "
                "WHERE evidence_object_id IN (SELECT id FROM evidence_object "
                "WHERE privacy_class = 'private')"
            )
            connection.execute(
                "UPDATE source SET privacy_class = 'private' WHERE id IN "
                "(SELECT source_id FROM node_attribute "
                "WHERE privacy_class = 'private')"
            )
            return self._ontology_snapshot_connection(connection)

    @staticmethod
    def _insert_import_provenance(
        connection: sqlite3.Connection,
        request: JsonlImportRequest,
        scan: JsonlScan,
        evidence: ImportEvidence,
        *,
        batch_id: str,
        idempotency_key: str,
        recorded_at: str,
    ) -> tuple[str, str]:
        source_id = stable_uuid("source", "jsonl", scan.content_hash)
        run_id = stable_uuid("analytical_run", idempotency_key)
        connection.execute(
            "INSERT INTO source "
            "(id, natural_key, kind, locator, privacy_class, recorded_at) "
            "VALUES (?, ?, 'jsonl', ?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (
                source_id,
                f"jsonl:{scan.content_hash}",
                f"evidence:sha256:{scan.content_hash}",
                evidence.object.privacy_class,
                recorded_at,
            ),
        )
        connection.execute(
            "INSERT INTO evidence_object "
            "(id, digest, byte_size, media_type, privacy_class, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (
                evidence.object.id,
                evidence.object.digest,
                evidence.object.byte_size,
                evidence.object.media_type,
                evidence.object.privacy_class,
                evidence.object.recorded_at,
            ),
        )
        connection.execute(
            "INSERT INTO evidence_fragment "
            "(id, evidence_object_id, locator_kind, locator_json, extractor_id, "
            "extractor_version, byte_size, digest, privacy_class, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (
                evidence.fragment.id,
                evidence.fragment.evidence_object_id,
                evidence.fragment.locator_kind,
                evidence.fragment.locator_json,
                evidence.fragment.extractor_id,
                evidence.fragment.extractor_version,
                evidence.fragment.byte_size,
                evidence.fragment.digest,
                evidence.fragment.privacy_class,
                evidence.fragment.recorded_at,
            ),
        )
        connection.execute(
            "INSERT INTO analytical_run "
            "(id, idempotency_key, batch_id, source_id, method, recorded_at) "
            "VALUES (?, ?, ?, ?, 'jsonl-import-v1', ?)",
            (run_id, idempotency_key, batch_id, source_id, recorded_at),
        )
        connection.execute(
            "INSERT INTO evidence_acquisition "
            "(id, evidence_object_id, source_id, run_id, privacy_class, "
            "retention_required, retain_until, method, review_status, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, 1, NULL, 'jsonl-import-v1', 'unreviewed', ?)",
            (
                stable_uuid("evidence_acquisition", evidence.object.id, run_id),
                evidence.object.id,
                source_id,
                run_id,
                evidence.object.privacy_class,
                recorded_at,
            ),
        )
        return source_id, run_id

    def import_jsonl(
        self,
        request: JsonlImportRequest,
        scan: JsonlScan,
        evidence: ImportEvidence,
    ) -> dict[str, Any]:
        from analytical_memory.jsonl import import_idempotency_key

        idempotency_key = import_idempotency_key(request, scan.content_hash)
        batch_id = stable_uuid("ingestion_batch", idempotency_key)
        namespace, node_type = split_entity_type(request.entity_type)
        recorded_at = _now()
        request_document = {
            "entity_type": request.entity_type,
            "key": [{"field": item.field, "type": item.type} for item in request.key],
        }
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                "SELECT input_hash, result_json FROM ingestion_batch "
                "WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if replay is not None:
                if str(replay["input_hash"]) != scan.content_hash:
                    raise ImportValidationError("idempotency key conflict")
                result = json.loads(str(replay["result_json"]))
                if not isinstance(result, dict):
                    raise ValueError("stored import result must be an object")
                result["replayed"] = True
                return result

            declaration_row = connection.execute(
                "SELECT * FROM entity_declaration WHERE entity_type = ?",
                (request.entity_type,),
            ).fetchone()
            declaration_fields = self._declaration_fields(
                None if declaration_row is None else str(declaration_row["fields_json"])
            )
            entity_privacy = (
                "public"
                if declaration_row is None
                else str(declaration_row["privacy_class"])
            )
            for name, specification in declaration_fields.items():
                if (
                    specification["required"]
                    and scan.present_counts.get(name, 0) != scan.record_count
                ):
                    raise ImportValidationError(f"required field {name!r} is missing")
                if not specification["nullable"] and name in scan.null_fields:
                    raise ImportValidationError(f"field {name!r} is not nullable")
                expected = specification.get("type")
                actual = scan.field_types.get(name)
                if expected is not None and actual is not None and expected != actual:
                    raise ImportValidationError(
                        f"field {name!r} has type {actual}, expected {expected}"
                    )
            existing_fields = {
                str(row["field_name"]): row
                for row in connection.execute(
                    "SELECT * FROM observed_field WHERE entity_type = ?",
                    (request.entity_type,),
                ).fetchall()
            }
            for name, actual in scan.field_types.items():
                row = existing_fields.get(name)
                if row is not None and str(row["json_type"]) not in {
                    "unresolved",
                    actual,
                }:
                    raise ImportValidationError(
                        f"field {name!r} already has type {row['json_type']}"
                    )

            connection.execute(
                "INSERT INTO ingestion_batch "
                "(id, idempotency_key, kind, input_hash, schema_fingerprint, "
                "request_json, result_json, recorded_at) "
                "VALUES (?, ?, 'jsonl-import', ?, ?, ?, '{}', ?)",
                (
                    batch_id,
                    idempotency_key,
                    scan.content_hash,
                    request.contract_fingerprint,
                    canonical_json(request_document),
                    recorded_at,
                ),
            )
            source_id, run_id = self._insert_import_provenance(
                connection,
                request,
                scan,
                evidence,
                batch_id=batch_id,
                idempotency_key=idempotency_key,
                recorded_at=recorded_at,
            )
            created_nodes = 0
            updated_nodes = 0
            attributes_written = 0
            for line_number, record in iter_jsonl(scan.spool_path):
                conditions = []
                parameters: list[Any] = [namespace, node_type]
                for selector in request.key:
                    conditions.append(
                        "EXISTS (SELECT 1 FROM node_attribute AS key_attribute "
                        "WHERE key_attribute.node_id = node.id "
                        "AND key_attribute.attribute_name = ? "
                        "AND key_attribute.value_json = ?)"
                    )
                    parameters.extend(
                        [selector.field, canonical_json(record[selector.field])]
                    )
                matches = connection.execute(
                    "SELECT node.id FROM node WHERE node.namespace = ? "
                    "AND node.type = ? AND " + " AND ".join(conditions) + " LIMIT 2",
                    parameters,
                ).fetchall()
                if len(matches) > 1:
                    raise ImportValidationError(
                        f"line {line_number}: ambiguous import key"
                    )
                if matches:
                    node_id = str(matches[0]["id"])
                    updated_nodes += 1
                else:
                    node_id = str(uuid.uuid4())
                    created_nodes += 1
                    connection.execute(
                        "INSERT INTO node "
                        "(id, namespace, type, display_label, privacy_class, "
                        "recorded_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?, ?)",
                        (
                            node_id,
                            namespace,
                            node_type,
                            entity_privacy,
                            recorded_at,
                            recorded_at,
                        ),
                    )
                for name, value in record.items():
                    specification = declaration_fields.get(name, {})
                    field_privacy = specification.get("privacy", entity_privacy)
                    existing = existing_fields.get(name)
                    effective_type = scan.field_types.get(name)
                    if effective_type is None and existing is not None:
                        effective_type = str(existing["json_type"])
                    if effective_type is None:
                        effective_type = specification.get("type") or "unresolved"
                    attribute_id = stable_uuid("node_attribute", node_id, name)
                    sort_text_folded, sort_text_exact, sort_number = _sort_values(value)
                    connection.execute(
                        "INSERT INTO node_attribute "
                        "(id, node_id, attribute_name, value_json, json_type, "
                        "privacy_class, searchable, source_id, batch_id, run_id, "
                        "fragment_id, updated_at, sort_text_folded, sort_text_exact, "
                        "sort_number) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(node_id, attribute_name) DO UPDATE SET "
                        "value_json = excluded.value_json, "
                        "json_type = excluded.json_type, "
                        "privacy_class = CASE WHEN "
                        "node_attribute.privacy_class = 'private' "
                        "THEN 'private' ELSE excluded.privacy_class END, "
                        "searchable = excluded.searchable, "
                        "source_id = excluded.source_id, "
                        "batch_id = excluded.batch_id, run_id = excluded.run_id, "
                        "fragment_id = excluded.fragment_id, "
                        "updated_at = excluded.updated_at, "
                        "sort_text_folded = excluded.sort_text_folded, "
                        "sort_text_exact = excluded.sort_text_exact, "
                        "sort_number = excluded.sort_number",
                        (
                            attribute_id,
                            node_id,
                            name,
                            canonical_json(value),
                            effective_type,
                            field_privacy,
                            int(specification.get("searchable", False)),
                            source_id,
                            batch_id,
                            run_id,
                            evidence.fragment.id,
                            recorded_at,
                            sort_text_folded,
                            sort_text_exact,
                            sort_number,
                        ),
                    )
                    searchable = bool(specification.get("searchable", False))
                    document_id = stable_uuid(
                        "search_document", attribute_id, 0, "attribute-text-v1"
                    )
                    connection.execute(
                        "DELETE FROM search_document_fts WHERE document_id = ?",
                        (document_id,),
                    )
                    if searchable and isinstance(value, str):
                        content_hash = sha256_bytes(value.encode("utf-8"))
                        connection.execute(
                            "INSERT INTO search_document "
                            "(id, target_kind, target_id, chunk_index, content, "
                            "content_hash, extraction_version, privacy_class, "
                            "lifecycle, recorded_at) "
                            "VALUES (?, 'node_attribute', ?, 0, ?, ?, "
                            "'attribute-text-v1', ?, 'active', ?) "
                            "ON CONFLICT(target_kind, target_id, chunk_index, "
                            "extraction_version) DO UPDATE SET "
                            "content = excluded.content, "
                            "content_hash = excluded.content_hash, "
                            "privacy_class = excluded.privacy_class, "
                            "lifecycle = 'active', recorded_at = excluded.recorded_at",
                            (
                                document_id,
                                attribute_id,
                                value,
                                content_hash,
                                field_privacy,
                                recorded_at,
                            ),
                        )
                        connection.execute(
                            "INSERT INTO search_document_fts(document_id, content) "
                            "VALUES (?, ?)",
                            (document_id, value),
                        )
                    else:
                        connection.execute(
                            "UPDATE search_document SET lifecycle = 'stale' "
                            "WHERE id = ?",
                            (document_id,),
                        )
                    attributes_written += 1
            all_fields = set(scan.present_counts) | set(declaration_fields)
            new_fields: list[str] = []
            resolved_types: list[str] = []
            for name in sorted(all_fields):
                specification = declaration_fields.get(name, {})
                existing = existing_fields.get(name)
                inferred = scan.field_types.get(name)
                effective_type = inferred or specification.get("type") or "unresolved"
                if existing is not None and str(existing["json_type"]) != "unresolved":
                    effective_type = str(existing["json_type"])
                if existing is None:
                    new_fields.append(name)
                elif (
                    str(existing["json_type"]) == "unresolved"
                    and effective_type != "unresolved"
                ):
                    resolved_types.append(name)
                connection.execute(
                    "INSERT INTO observed_field "
                    "(entity_type, field_name, json_type, privacy_class, required, "
                    "nullable, searchable, declared, first_batch_id, last_batch_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(entity_type, field_name) DO UPDATE SET "
                    "json_type = CASE WHEN observed_field.json_type = 'unresolved' "
                    "THEN excluded.json_type ELSE observed_field.json_type END, "
                    "privacy_class = CASE WHEN "
                    "observed_field.privacy_class = 'private' "
                    "THEN 'private' ELSE excluded.privacy_class END, "
                    "last_batch_id = excluded.last_batch_id",
                    (
                        request.entity_type,
                        name,
                        effective_type,
                        specification.get("privacy", entity_privacy),
                        int(specification.get("required", False)),
                        int(specification.get("nullable", True)),
                        int(specification.get("searchable", False)),
                        int(name in declaration_fields),
                        batch_id,
                        batch_id,
                    ),
                )
                _backfill_attribute_type(
                    connection, request.entity_type, name, effective_type
                )
            snapshot = self._ontology_snapshot_connection(connection)
            result = {
                "attributes_written": attributes_written,
                "batch_id": batch_id,
                "created_nodes": created_nodes,
                "evidence_digest": scan.content_hash,
                "fragment_id": evidence.fragment.id,
                "idempotency_key": idempotency_key,
                "ontology_delta": {
                    "new_entities": [request.entity_type]
                    if not existing_fields and declaration_row is None
                    else [],
                    "new_fields": new_fields,
                    "resolved_types": resolved_types,
                },
                "ontology_fingerprint": snapshot["ontology_fingerprint"],
                "records": scan.record_count,
                "replayed": False,
                "run_id": run_id,
                "source_id": source_id,
                "updated_nodes": updated_nodes,
            }
            connection.execute(
                "UPDATE ingestion_batch SET result_json = ? WHERE id = ?",
                (canonical_json(result), batch_id),
            )
            return result

    def write_analytical_attribute(
        self,
        request: AnalyticalAttributeRequest,
        evidence: ImportEvidence,
    ) -> dict[str, Any]:
        actual_type = json_type(request.value)
        recorded_at = _now()
        source_id = stable_uuid("source", "analytical-result", evidence.object.digest)
        run_id = stable_uuid("analytical_run", request.idempotency_key)
        attribute_id = stable_uuid(
            "node_attribute", request.node_id, request.attribute_name
        )
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            node = connection.execute(
                "SELECT namespace, type FROM node WHERE id = ?", (request.node_id,)
            ).fetchone()
            if node is None:
                raise RecordNotFoundError(f"node not found: {request.node_id}")
            entity_type = f"{node['namespace']}.{node['type']}"
            field = connection.execute(
                "SELECT * FROM observed_field WHERE entity_type = ? AND field_name = ?",
                (entity_type, request.attribute_name),
            ).fetchone()
            known_type = None if field is None else str(field["json_type"])
            if actual_type is not None and known_type not in {
                None,
                "unresolved",
                actual_type,
            }:
                raise ImportValidationError(
                    f"field {request.attribute_name!r} already has type {known_type}"
                )
            effective_type = actual_type or known_type or "unresolved"
            existing_run = connection.execute(
                "SELECT id FROM analytical_run WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing_run is not None:
                return {
                    "attribute_id": attribute_id,
                    "evidence_digest": evidence.object.digest,
                    "fragment_id": evidence.fragment.id,
                    "idempotency_key": request.idempotency_key,
                    "ontology_fingerprint": self._ontology_snapshot_connection(
                        connection
                    )["ontology_fingerprint"],
                    "replayed": True,
                    "run_id": str(existing_run["id"]),
                    "source_id": source_id,
                }
            connection.execute(
                "INSERT INTO source "
                "(id, natural_key, kind, locator, privacy_class, recorded_at) "
                "VALUES (?, ?, 'analytical-result', ?, ?, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (
                    source_id,
                    f"analytical-result:{evidence.object.digest}",
                    f"evidence:sha256:{evidence.object.digest}",
                    request.privacy,
                    recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_object "
                "(id, digest, byte_size, media_type, privacy_class, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (
                    evidence.object.id,
                    evidence.object.digest,
                    evidence.object.byte_size,
                    evidence.object.media_type,
                    evidence.object.privacy_class,
                    evidence.object.recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_fragment "
                "(id, evidence_object_id, locator_kind, locator_json, extractor_id, "
                "extractor_version, byte_size, digest, privacy_class, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (
                    evidence.fragment.id,
                    evidence.fragment.evidence_object_id,
                    evidence.fragment.locator_kind,
                    evidence.fragment.locator_json,
                    evidence.fragment.extractor_id,
                    evidence.fragment.extractor_version,
                    evidence.fragment.byte_size,
                    evidence.fragment.digest,
                    evidence.fragment.privacy_class,
                    evidence.fragment.recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO analytical_run "
                "(id, idempotency_key, batch_id, source_id, method, recorded_at) "
                "VALUES (?, ?, NULL, ?, ?, ?)",
                (
                    run_id,
                    request.idempotency_key,
                    source_id,
                    request.method,
                    recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_acquisition "
                "(id, evidence_object_id, source_id, run_id, privacy_class, "
                "retention_required, retain_until, method, review_status, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, 1, NULL, ?, 'unreviewed', ?)",
                (
                    stable_uuid("evidence_acquisition", evidence.object.id, run_id),
                    evidence.object.id,
                    source_id,
                    run_id,
                    request.privacy,
                    request.method,
                    recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO node_attribute "
                "(id, node_id, attribute_name, value_json, json_type, privacy_class, "
                "searchable, source_id, batch_id, run_id, fragment_id, updated_at, "
                "sort_text_folded, sort_text_exact, sort_number) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(node_id, attribute_name) DO UPDATE SET "
                "value_json = excluded.value_json, json_type = excluded.json_type, "
                "privacy_class = CASE WHEN node_attribute.privacy_class = 'private' "
                "THEN 'private' ELSE excluded.privacy_class END, "
                "searchable = excluded.searchable, source_id = excluded.source_id, "
                "batch_id = NULL, run_id = excluded.run_id, "
                "fragment_id = excluded.fragment_id, updated_at = excluded.updated_at, "
                "sort_text_folded = excluded.sort_text_folded, "
                "sort_text_exact = excluded.sort_text_exact, "
                "sort_number = excluded.sort_number",
                (
                    attribute_id,
                    request.node_id,
                    request.attribute_name,
                    canonical_json(request.value),
                    effective_type,
                    request.privacy,
                    int(request.searchable),
                    source_id,
                    run_id,
                    evidence.fragment.id,
                    recorded_at,
                    *_sort_values(request.value),
                ),
            )
            document_id = stable_uuid(
                "search_document", attribute_id, 0, "attribute-text-v1"
            )
            connection.execute(
                "DELETE FROM search_document_fts WHERE document_id = ?", (document_id,)
            )
            if request.searchable and isinstance(request.value, str):
                content_hash = sha256_bytes(request.value.encode("utf-8"))
                connection.execute(
                    "INSERT INTO search_document "
                    "(id, target_kind, target_id, chunk_index, content, content_hash, "
                    "extraction_version, privacy_class, lifecycle, recorded_at) "
                    "VALUES (?, 'node_attribute', ?, 0, ?, ?, "
                    "'attribute-text-v1', ?, 'active', ?) "
                    "ON CONFLICT(target_kind, target_id, chunk_index, "
                    "extraction_version) DO UPDATE SET content = excluded.content, "
                    "content_hash = excluded.content_hash, "
                    "privacy_class = excluded.privacy_class, lifecycle = 'active', "
                    "recorded_at = excluded.recorded_at",
                    (
                        document_id,
                        attribute_id,
                        request.value,
                        content_hash,
                        request.privacy,
                        recorded_at,
                    ),
                )
                connection.execute(
                    "INSERT INTO search_document_fts(document_id, content) "
                    "VALUES (?, ?)",
                    (document_id, request.value),
                )
            else:
                connection.execute(
                    "UPDATE search_document SET lifecycle = 'stale' WHERE id = ?",
                    (document_id,),
                )
            connection.execute(
                "INSERT INTO observed_field "
                "(entity_type, field_name, json_type, privacy_class, required, "
                "nullable, searchable, declared, first_batch_id, last_batch_id) "
                "VALUES (?, ?, ?, ?, 0, 1, ?, 0, NULL, NULL) "
                "ON CONFLICT(entity_type, field_name) DO UPDATE SET "
                "json_type = CASE WHEN observed_field.json_type = 'unresolved' "
                "THEN excluded.json_type ELSE observed_field.json_type END, "
                "privacy_class = CASE WHEN observed_field.privacy_class = 'private' "
                "THEN 'private' ELSE excluded.privacy_class END",
                (
                    entity_type,
                    request.attribute_name,
                    effective_type,
                    request.privacy,
                    int(request.searchable),
                ),
            )
            _backfill_attribute_type(
                connection, entity_type, request.attribute_name, effective_type
            )
            snapshot = self._ontology_snapshot_connection(connection)
            return {
                "attribute_id": attribute_id,
                "evidence_digest": evidence.object.digest,
                "fragment_id": evidence.fragment.id,
                "idempotency_key": request.idempotency_key,
                "ontology_fingerprint": snapshot["ontology_fingerprint"],
                "replayed": False,
                "run_id": run_id,
                "source_id": source_id,
            }

    def materialize_join(
        self, request: JoinRequest, evidence: ImportEvidence
    ) -> dict[str, Any]:
        if not request.name or not request.relation:
            raise JoinConflictError("join name and relation must not be empty")
        if not request.from_.fields or len(request.from_.fields) != len(
            request.to.fields
        ):
            raise JoinConflictError("join endpoints require equally sized fields")
        split_entity_type(request.from_.type)
        split_entity_type(request.to.type)
        definition = {
            "from": {"fields": list(request.from_.fields), "type": request.from_.type},
            "name": request.name,
            "relation": request.relation,
            "to": {"fields": list(request.to.fields), "type": request.to.type},
        }
        definition_hash = sha256_json(definition)
        idempotency_key = request.idempotency_key or str(uuid.uuid4())
        batch_id = stable_uuid("ingestion_batch", "join", idempotency_key)
        source_id = stable_uuid("source", "join-declaration", definition_hash)
        run_id = stable_uuid("analytical_run", "join", idempotency_key)
        recorded_at = _now()
        from_namespace, from_type = split_entity_type(request.from_.type)
        to_namespace, to_type = split_entity_type(request.to.type)
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                "SELECT input_hash, result_json FROM ingestion_batch "
                "WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if replay is not None:
                if str(replay["input_hash"]) != definition_hash:
                    raise JoinConflictError("join idempotency key conflict")
                result = json.loads(str(replay["result_json"]))
                if not isinstance(result, dict):
                    raise ValueError("stored join result must be an object")
                result["replayed"] = True
                return result
            existing_declaration = connection.execute(
                "SELECT * FROM ontology_declaration WHERE name = ?",
                (request.name,),
            ).fetchone()
            if (
                existing_declaration is not None
                and str(existing_declaration["definition_hash"]) != definition_hash
            ):
                raise JoinConflictError(
                    f"join name {request.name!r} already has another definition"
                )
            type_pairs = zip(request.from_.fields, request.to.fields, strict=True)
            for from_field, to_field in type_pairs:
                from_row = connection.execute(
                    "SELECT json_type FROM observed_field "
                    "WHERE entity_type = ? AND field_name = ?",
                    (request.from_.type, from_field),
                ).fetchone()
                to_row = connection.execute(
                    "SELECT json_type FROM observed_field "
                    "WHERE entity_type = ? AND field_name = ?",
                    (request.to.type, to_field),
                ).fetchone()
                if from_row is None or to_row is None:
                    raise JoinConflictError("join references an unknown field")
                if str(from_row["json_type"]) == "unresolved" or str(
                    from_row["json_type"]
                ) != str(to_row["json_type"]):
                    raise JoinConflictError("join fields have incompatible types")
            connection.execute(
                "INSERT INTO ingestion_batch "
                "(id, idempotency_key, kind, input_hash, schema_fingerprint, "
                "request_json, result_json, recorded_at) "
                "VALUES (?, ?, 'join-materialization', ?, ?, ?, '{}', ?)",
                (
                    batch_id,
                    idempotency_key,
                    definition_hash,
                    request.contract_fingerprint,
                    canonical_json(definition),
                    recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO source "
                "(id, natural_key, kind, locator, privacy_class, recorded_at) "
                "VALUES (?, ?, 'join-declaration', ?, 'public', ?) "
                "ON CONFLICT(id) DO NOTHING",
                (
                    source_id,
                    f"join-declaration:{definition_hash}",
                    f"evidence:sha256:{evidence.object.digest}",
                    recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_object "
                "(id, digest, byte_size, media_type, privacy_class, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (
                    evidence.object.id,
                    evidence.object.digest,
                    evidence.object.byte_size,
                    evidence.object.media_type,
                    evidence.object.privacy_class,
                    evidence.object.recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_fragment "
                "(id, evidence_object_id, locator_kind, locator_json, extractor_id, "
                "extractor_version, byte_size, digest, privacy_class, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (
                    evidence.fragment.id,
                    evidence.fragment.evidence_object_id,
                    evidence.fragment.locator_kind,
                    evidence.fragment.locator_json,
                    evidence.fragment.extractor_id,
                    evidence.fragment.extractor_version,
                    evidence.fragment.byte_size,
                    evidence.fragment.digest,
                    evidence.fragment.privacy_class,
                    evidence.fragment.recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO analytical_run "
                "(id, idempotency_key, batch_id, source_id, method, recorded_at) "
                "VALUES (?, ?, ?, ?, 'join-materialization-v1', ?)",
                (run_id, f"join:{idempotency_key}", batch_id, source_id, recorded_at),
            )
            connection.execute(
                "INSERT INTO evidence_acquisition "
                "(id, evidence_object_id, source_id, run_id, privacy_class, "
                "retention_required, retain_until, method, review_status, recorded_at) "
                "VALUES (?, ?, ?, ?, 'public', 1, NULL, "
                "'join-materialization-v1', 'unreviewed', ?)",
                (
                    stable_uuid("evidence_acquisition", evidence.object.id, run_id),
                    evidence.object.id,
                    source_id,
                    run_id,
                    recorded_at,
                ),
            )
            if existing_declaration is None:
                connection.execute(
                    "INSERT INTO ontology_declaration "
                    "(name, kind, relation_type, from_entity, from_fields_json, "
                    "to_entity, to_fields_json, definition_hash, enabled, source_id, "
                    "fragment_id, recorded_at) "
                    "VALUES (?, 'join', ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                    (
                        request.name,
                        request.relation,
                        request.from_.type,
                        canonical_json(list(request.from_.fields)),
                        request.to.type,
                        canonical_json(list(request.to.fields)),
                        definition_hash,
                        source_id,
                        evidence.fragment.id,
                        recorded_at,
                    ),
                )
            source_nodes = connection.execute(
                "SELECT id FROM node WHERE namespace = ? AND type = ? ORDER BY id",
                (from_namespace, from_type),
            ).fetchall()
            created = 0
            skipped_null_or_missing = 0
            skipped_unmatched = 0
            previous_active = 0
            previous_inactive = 0
            for source_node in source_nodes:
                source_node_id = str(source_node["id"])
                key_values: list[tuple[str, str]] = []
                missing = False
                for field in request.from_.fields:
                    row = connection.execute(
                        "SELECT value_json, json_type FROM node_attribute "
                        "WHERE node_id = ? AND attribute_name = ?",
                        (source_node_id, field),
                    ).fetchone()
                    if row is None or str(row["value_json"]) == "null":
                        missing = True
                        break
                    key_values.append((str(row["value_json"]), str(row["json_type"])))
                if missing:
                    skipped_null_or_missing += 1
                    continue
                target_conditions = []
                target_parameters: list[Any] = [to_namespace, to_type]
                for field, (value_json, effective_type) in zip(
                    request.to.fields, key_values, strict=True
                ):
                    target_conditions.append(
                        "EXISTS (SELECT 1 FROM node_attribute AS target_attribute "
                        "WHERE target_attribute.node_id = node.id "
                        "AND target_attribute.attribute_name = ? "
                        "AND target_attribute.json_type = ? "
                        "AND target_attribute.value_json = ?)"
                    )
                    target_parameters.extend([field, effective_type, value_json])
                targets = connection.execute(
                    "SELECT node.id, node.privacy_class FROM node "
                    "WHERE node.namespace = ? AND node.type = ? AND "
                    + " AND ".join(target_conditions)
                    + " LIMIT 2",
                    target_parameters,
                ).fetchall()
                if len(targets) > 1:
                    raise AmbiguousTargetError(
                        f"ambiguous_target for source node {source_node_id}"
                    )
                if not targets:
                    skipped_unmatched += 1
                    continue
                target_node_id = str(targets[0]["id"])
                existing_relation = connection.execute(
                    "SELECT id, active FROM relation WHERE source_node_id = ? "
                    "AND type = ? AND target_node_id = ? AND logical_key = ?",
                    (
                        source_node_id,
                        request.relation,
                        target_node_id,
                        request.name,
                    ),
                ).fetchone()
                if existing_relation is not None:
                    if bool(existing_relation["active"]):
                        previous_active += 1
                    else:
                        previous_inactive += 1
                    continue
                source_privacy = connection.execute(
                    "SELECT privacy_class FROM node WHERE id = ?", (source_node_id,)
                ).fetchone()[0]
                privacy = (
                    "private"
                    if "private"
                    in {str(source_privacy), str(targets[0]["privacy_class"])}
                    else "public"
                )
                relation_id = stable_uuid(
                    "relation",
                    source_node_id,
                    request.relation,
                    target_node_id,
                    request.name,
                )
                connection.execute(
                    "INSERT INTO relation "
                    "(id, source_node_id, type, target_node_id, logical_key, active, "
                    "privacy_class, source_id, batch_id, run_id, fragment_id, "
                    "updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                    (
                        relation_id,
                        source_node_id,
                        request.relation,
                        target_node_id,
                        request.name,
                        privacy,
                        source_id,
                        batch_id,
                        run_id,
                        evidence.fragment.id,
                        recorded_at,
                    ),
                )
                created += 1
            snapshot = self._ontology_snapshot_connection(connection)
            result = {
                "batch_id": batch_id,
                "created_relations": created,
                "declaration_created": existing_declaration is None,
                "definition_hash": definition_hash,
                "name": request.name,
                "ontology_fingerprint": snapshot["ontology_fingerprint"],
                "previously_materialized_active": previous_active,
                "previously_materialized_inactive": previous_inactive,
                "replayed": False,
                "run_id": run_id,
                "skipped_null_or_missing": skipped_null_or_missing,
                "skipped_unmatched": skipped_unmatched,
                "source_id": source_id,
            }
            connection.execute(
                "UPDATE ingestion_batch SET result_json = ? WHERE id = ?",
                (canonical_json(result), batch_id),
            )
            return result

    @staticmethod
    def _field_type(
        connection: sqlite3.Connection, entity_type: str, field_name: str
    ) -> str:
        row = connection.execute(
            "SELECT json_type FROM observed_field "
            "WHERE entity_type = ? AND field_name = ?",
            (entity_type, field_name),
        ).fetchone()
        if row is None:
            raise QueryValidationError(f"unknown field {entity_type}.{field_name}")
        return str(row["json_type"])

    def execute_query(self, plan: QueryPlan) -> dict[str, Any]:
        alias_entities = dict(plan.node_aliases)
        field_references: set[str] = set()
        for predicate in plan.predicates:
            field_references.add(str(predicate["field"]))
        for projection in plan.projections:
            if "field" in projection:
                field_references.add(str(projection["field"]))
        for ordering in plan.order_by:
            field_references.add(str(ordering["field"]))
        ordered_fields = sorted(field_references)
        field_aliases = {
            reference: f"a{index}" for index, reference in enumerate(ordered_fields)
        }
        node_sql_aliases = {
            alias: f"n{index}" for index, (alias, _) in enumerate(plan.node_aliases)
        }
        with self._connect() as connection:
            effective_types: dict[str, str] = {}
            for reference in ordered_fields:
                alias, _, field_name = reference.partition(".")
                effective_types[reference] = self._field_type(
                    connection, alias_entities[alias], field_name
                )
            first_alias = plan.node_aliases[0][0]
            sql = f"FROM node AS {node_sql_aliases[first_alias]} "
            sql_parameters: list[Any] = []
            for alias, _ in plan.node_aliases[1:]:
                sql += f"CROSS JOIN node AS {node_sql_aliases[alias]} "
            for index, edge in enumerate(plan.edges):
                relation_alias = f"r{index}"
                source_alias = node_sql_aliases[edge["from"]]
                target_alias = node_sql_aliases[edge["to"]]
                sql += (
                    f"JOIN relation AS {relation_alias} ON "
                    f"{relation_alias}.source_node_id = {source_alias}.id "
                    f"AND {relation_alias}.target_node_id = {target_alias}.id "
                    f"AND {relation_alias}.type = ? AND {relation_alias}.active = 1 "
                )
                sql_parameters.append(edge["type"])
                if "logical_key" in edge:
                    sql += f"AND {relation_alias}.logical_key = ? "
                    sql_parameters.append(edge["logical_key"])
            for reference in ordered_fields:
                alias, _, field_name = reference.partition(".")
                attribute_alias = field_aliases[reference]
                sql += (
                    f"LEFT JOIN node_attribute AS {attribute_alias} ON "
                    f"{attribute_alias}.node_id = {node_sql_aliases[alias]}.id "
                    f"AND {attribute_alias}.attribute_name = ? "
                )
                sql_parameters.append(field_name)
            conditions: list[str] = []
            for alias, entity_type in plan.node_aliases:
                namespace, node_type = split_entity_type(entity_type)
                node_alias = node_sql_aliases[alias]
                conditions.extend(
                    [f"{node_alias}.namespace = ?", f"{node_alias}.type = ?"]
                )
                sql_parameters.extend([namespace, node_type])
            always_empty = False
            for predicate in plan.predicates:
                reference = str(predicate["field"])
                attribute_alias = field_aliases[reference]
                operator = str(predicate["op"])
                effective_type = effective_types[reference]
                if operator == "exists":
                    conditions.append(f"{attribute_alias}.id IS NOT NULL")
                    continue
                if effective_type == "unresolved":
                    always_empty = True
                    continue
                values = predicate.get("values", [predicate.get("value")])
                for value in values:
                    actual_type = json_type(value)
                    if actual_type is not None and actual_type != effective_type:
                        raise QueryValidationError(
                            f"literal type {actual_type} conflicts with "
                            f"{effective_type} "
                            f"for {reference}"
                        )
                conditions.append(f"{attribute_alias}.json_type = ?")
                sql_parameters.append(effective_type)
                if operator in {"eq", "ne"}:
                    symbol = "=" if operator == "eq" else "<>"
                    conditions.append(f"{attribute_alias}.value_json {symbol} ?")
                    sql_parameters.append(canonical_json(predicate["value"]))
                elif operator == "in":
                    placeholders = ", ".join("?" for _ in values)
                    conditions.append(
                        f"{attribute_alias}.value_json IN ({placeholders})"
                    )
                    sql_parameters.extend(canonical_json(value) for value in values)
                else:
                    if effective_type not in {"number", "string"}:
                        raise QueryValidationError(
                            f"{operator} is not supported for {effective_type}"
                        )
                    symbols = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
                    if effective_type == "number":
                        conditions.append(
                            f"{attribute_alias}.sort_number {symbols[operator]} ?"
                        )
                        sql_parameters.append(float(predicate["value"]))
                    else:
                        value = str(predicate["value"])
                        folded = value.casefold()
                        primary = f"{attribute_alias}.sort_text_folded"
                        secondary = f"{attribute_alias}.sort_text_exact"
                        if operator in {"lt", "lte"}:
                            secondary_symbol = "<" if operator == "lt" else "<="
                            conditions.append(
                                f"({primary} < ? OR ({primary} = ? AND "
                                f"{secondary} {secondary_symbol} ?))"
                            )
                        else:
                            secondary_symbol = ">" if operator == "gt" else ">="
                            conditions.append(
                                f"({primary} > ? OR ({primary} = ? AND "
                                f"{secondary} {secondary_symbol} ?))"
                            )
                        sql_parameters.extend([folded, folded, value])
            if always_empty:
                conditions.append("0 = 1")
            where_sql = " WHERE " + " AND ".join(conditions)
            if plan.count:
                total = int(
                    connection.execute(
                        "SELECT COUNT(*) " + sql + where_sql, sql_parameters
                    ).fetchone()[0]
                )
                snapshot = self._ontology_snapshot_connection(connection)
                return {
                    "count": total,
                    "ontology_fingerprint": snapshot["ontology_fingerprint"],
                    "ordering": [],
                    "rows": [],
                    "truncated": False,
                }
            select_columns: list[str] = [
                f"{node_sql_aliases[alias]}.id AS b{index}"
                for index, (alias, _) in enumerate(plan.node_aliases)
            ]
            for index, projection in enumerate(plan.projections):
                reference = str(projection["field"])
                attribute_alias = field_aliases[reference]
                for column in (
                    "id",
                    "value_json",
                    "json_type",
                    "source_id",
                    "batch_id",
                    "run_id",
                    "fragment_id",
                    "updated_at",
                ):
                    select_columns.append(
                        f"{attribute_alias}.{column} AS p{index}_{column}"
                    )
            ordering_sql: list[str] = []
            for item in plan.order_by:
                attribute_alias = field_aliases[item["field"]]
                direction = item["direction"].upper()
                effective_type = effective_types[item["field"]]
                if effective_type == "string":
                    value_order = (
                        f"{attribute_alias}.sort_text_folded {direction}, "
                        f"{attribute_alias}.sort_text_exact {direction}"
                    )
                elif effective_type == "number":
                    value_order = f"{attribute_alias}.sort_number {direction}"
                else:
                    value_order = f"{attribute_alias}.value_json {direction}"
                ordering_sql.append(
                    f"({attribute_alias}.id IS NULL) ASC, {value_order}"
                )
            ordering_sql.extend(
                f"{node_sql_aliases[alias]}.id ASC" for alias, _ in plan.node_aliases
            )
            query = (
                "SELECT "
                + ", ".join(select_columns)
                + " "
                + sql
                + where_sql
                + " ORDER BY "
                + ", ".join(ordering_sql)
                + " LIMIT ? OFFSET ?"
            )
            rows = connection.execute(
                query, [*sql_parameters, plan.limit + 1, plan.offset]
            ).fetchall()
            selected = rows[: plan.limit]
            results: list[dict[str, Any]] = []
            binding_indexes = {
                alias: index for index, (alias, _) in enumerate(plan.node_aliases)
            }
            for row in selected:
                projections: list[dict[str, Any]] = []
                for index, projection in enumerate(plan.projections):
                    record_id = row[f"p{index}_id"]
                    projections.append(
                        {
                            "batch_id": row[f"p{index}_batch_id"],
                            "field": projection["field"],
                            "fragment_id": row[f"p{index}_fragment_id"],
                            "json_type": effective_types[str(projection["field"])],
                            "node_id": str(
                                row[
                                    f"b{binding_indexes[str(projection['field']).partition('.')[0]]}"
                                ]
                            ),
                            "record_id": record_id,
                            "run_id": row[f"p{index}_run_id"],
                            "source_id": row[f"p{index}_source_id"],
                            "updated_at": row[f"p{index}_updated_at"],
                            "value": None
                            if record_id is None
                            else json.loads(str(row[f"p{index}_value_json"])),
                        }
                    )
                results.append(
                    {
                        "bindings": {
                            alias: str(row[f"b{index}"])
                            for index, (alias, _) in enumerate(plan.node_aliases)
                        },
                        "projections": projections,
                    }
                )
            snapshot = self._ontology_snapshot_connection(connection)
            effective_ordering: list[dict[str, str]] = [
                dict(item) for item in plan.order_by
            ]
            effective_ordering.extend(
                {"direction": "asc", "tie_breaker": f"{alias}.node_id"}
                for alias, _ in plan.node_aliases
            )
            return {
                "ontology_fingerprint": snapshot["ontology_fingerprint"],
                "ordering": effective_ordering,
                "rows": results,
                "truncated": len(rows) > plan.limit,
            }

    def deactivate_relation(self, relation_id: str) -> dict[str, Any]:
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM relation WHERE id = ?", (relation_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"relation not found: {relation_id}")
            updated_at = str(row["updated_at"])
            if bool(row["active"]):
                updated_at = _now()
                connection.execute(
                    "UPDATE relation SET active = 0, updated_at = ? WHERE id = ?",
                    (updated_at, relation_id),
                )
            return {
                "active": False,
                "batch_id": None if row["batch_id"] is None else str(row["batch_id"]),
                "fragment_id": (
                    None if row["fragment_id"] is None else str(row["fragment_id"])
                ),
                "logical_key": str(row["logical_key"]),
                "privacy_class": str(row["privacy_class"]),
                "relation_id": str(row["id"]),
                "relation_type": str(row["type"]),
                "run_id": None if row["run_id"] is None else str(row["run_id"]),
                "source_id": str(row["source_id"]),
                "source_node_id": str(row["source_node_id"]),
                "target_node_id": str(row["target_node_id"]),
                "updated_at": updated_at,
            }

    def delete_node(self, node_id: str) -> dict[str, int]:
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if (
                connection.execute(
                    "SELECT 1 FROM node WHERE id = ?", (node_id,)
                ).fetchone()
                is None
            ):
                raise RecordNotFoundError(f"node not found: {node_id}")
            attributes = int(
                connection.execute(
                    "SELECT COUNT(*) FROM node_attribute WHERE node_id = ?", (node_id,)
                ).fetchone()[0]
            )
            relations = int(
                connection.execute(
                    "SELECT COUNT(*) FROM relation "
                    "WHERE source_node_id = ? OR target_node_id = ?",
                    (node_id, node_id),
                ).fetchone()[0]
            )
            search_documents = int(
                connection.execute(
                    "SELECT COUNT(*) FROM search_document WHERE target_id IN "
                    "(SELECT id FROM node_attribute WHERE node_id = ?)",
                    (node_id,),
                ).fetchone()[0]
            )
            embeddings = int(
                connection.execute(
                    "SELECT COUNT(*) FROM embedding_record WHERE search_document_id IN "
                    "(SELECT id FROM search_document WHERE target_id IN "
                    "(SELECT id FROM node_attribute WHERE node_id = ?))",
                    (node_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "DELETE FROM search_document_fts WHERE document_id IN "
                "(SELECT id FROM search_document WHERE target_id IN "
                "(SELECT id FROM node_attribute WHERE node_id = ?))",
                (node_id,),
            )
            connection.execute("DELETE FROM node WHERE id = ?", (node_id,))
            return {
                "attributes": attributes,
                "embeddings": embeddings,
                "nodes": 1,
                "relations": relations,
                "search_documents": search_documents,
            }

    def export_current(self) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as connection:
            node_rows = connection.execute(
                "SELECT id, namespace, type, display_label, privacy_class, "
                "recorded_at, updated_at FROM node "
                "WHERE privacy_class = 'public' ORDER BY id"
            ).fetchall()
            attribute_rows = connection.execute(
                "SELECT attribute.id, attribute.node_id, attribute.attribute_name, "
                "attribute.value_json, attribute.json_type, "
                "attribute.privacy_class, attribute.source_id, attribute.batch_id, "
                "attribute.run_id, attribute.fragment_id, attribute.updated_at "
                "FROM node_attribute AS attribute "
                "JOIN node ON node.id = attribute.node_id "
                "WHERE attribute.privacy_class = 'public' "
                "AND node.privacy_class = 'public' ORDER BY attribute.id"
            ).fetchall()
            relation_rows = connection.execute(
                "SELECT relation.* FROM relation "
                "JOIN node AS source ON source.id = relation.source_node_id "
                "JOIN node AS target ON target.id = relation.target_node_id "
                "WHERE relation.privacy_class = 'public' "
                "AND source.privacy_class = 'public' "
                "AND target.privacy_class = 'public' ORDER BY relation.id"
            ).fetchall()
        attributes = []
        for row in attribute_rows:
            item = dict(row)
            item["value"] = json.loads(str(item.pop("value_json")))
            attributes.append(item)
        return {
            "attributes": attributes,
            "nodes": [dict(row) for row in node_rows],
            "relations": [dict(row) for row in relation_rows],
        }

    def traverse_relations(
        self,
        start_node_id: str,
        *,
        relation_types: list[str] | None,
        direction: str,
        max_depth: int,
        limit: int,
        states: list[str],
    ) -> dict[str, Any]:
        del states
        start = self.get_node(start_node_id)
        nodes: list[dict[str, Any]] = [{**start, "depth": 0}]
        edges: list[dict[str, Any]] = []
        visited_nodes = {start_node_id}
        visited_edges: set[str] = set()
        frontier = [start_node_id]
        truncated = False
        with self._connect() as connection:
            for depth in range(1, max_depth + 1):
                if not frontier or len(edges) >= limit:
                    truncated = bool(frontier)
                    break
                placeholders = ", ".join("?" for _ in frontier)
                clauses: list[str] = []
                parameters: list[Any] = []
                if direction in {"outbound", "both"}:
                    clauses.append(f"relation.source_node_id IN ({placeholders})")
                    parameters.extend(frontier)
                if direction in {"inbound", "both"}:
                    clauses.append(f"relation.target_node_id IN ({placeholders})")
                    parameters.extend(frontier)
                type_clause = ""
                if relation_types:
                    type_placeholders = ", ".join("?" for _ in relation_types)
                    type_clause = f" AND relation.type IN ({type_placeholders})"
                    parameters.extend(relation_types)
                rows = connection.execute(
                    "SELECT relation.*, source.namespace AS source_namespace, "
                    "source.type AS source_type, "
                    "source.privacy_class AS source_privacy, "
                    "target.namespace AS target_namespace, target.type AS target_type, "
                    "target.privacy_class AS target_privacy FROM relation "
                    "JOIN node AS source ON source.id = relation.source_node_id "
                    "JOIN node AS target ON target.id = relation.target_node_id "
                    f"WHERE relation.active = 1 AND ({' OR '.join(clauses)})"
                    + type_clause
                    + " ORDER BY relation.id LIMIT ?",
                    [*parameters, limit - len(edges) + 1],
                ).fetchall()
                if len(rows) > limit - len(edges):
                    truncated = True
                    rows = rows[: limit - len(edges)]
                next_frontier: list[str] = []
                for row in rows:
                    relation_id = str(row["id"])
                    if relation_id in visited_edges:
                        continue
                    visited_edges.add(relation_id)
                    source = {
                        "id": str(row["source_node_id"]),
                        "namespace": str(row["source_namespace"]),
                        "type": str(row["source_type"]),
                        "privacy_class": str(row["source_privacy"]),
                    }
                    target = {
                        "id": str(row["target_node_id"]),
                        "namespace": str(row["target_namespace"]),
                        "type": str(row["target_type"]),
                        "privacy_class": str(row["target_privacy"]),
                    }
                    edges.append(
                        {
                            "active": True,
                            "depth": depth,
                            "logical_key": str(row["logical_key"]),
                            "privacy_class": str(row["privacy_class"]),
                            "relation_id": relation_id,
                            "relation_type": str(row["type"]),
                            "source": source,
                            "target": target,
                        }
                    )
                    for node in (source, target):
                        if node["id"] not in visited_nodes:
                            visited_nodes.add(str(node["id"]))
                            next_frontier.append(str(node["id"]))
                            nodes.append({**node, "depth": depth})
                frontier = next_frontier
                if truncated:
                    break
        return {
            "direction": direction,
            "edges": edges,
            "max_depth": max_depth,
            "nodes": nodes,
            "query": "traverse-relations",
            "start_node_id": start_node_id,
            "states": ["active"],
            "truncated": truncated,
        }

    def get_node(self, node_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, namespace, type, display_label, "
                "privacy_class FROM node WHERE id = ?",
                (node_id,),
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"node not found: {node_id}")
        return {
            "id": str(row["id"]),
            "namespace": str(row["namespace"]),
            "type": str(row["type"]),
            "display_label": (
                None if row["display_label"] is None else str(row["display_label"])
            ),
            "privacy_class": str(row["privacy_class"]),
        }

    def current_metric(
        self, definition_version: str, dimensions_json: str
    ) -> dict[str, Any] | None:
        dimensions_hash = sha256_bytes(dimensions_json.encode("utf-8"))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT metric.*, analytical_run.recorded_at AS run_recorded_at,
                       analytical_run.method AS run_method,
                       analytical_run.source_id
                FROM metric
                JOIN analytical_run ON analytical_run.id = metric.run_id
                WHERE metric.definition_version = ?
                  AND metric.dimensions_hash = ?
                  AND metric.complete = 1
                  AND metric.invalidated = 0
                ORDER BY analytical_run.recorded_at DESC,
                         analytical_run.id DESC,
                         metric.id DESC
                LIMIT 1
                """,
                (definition_version, dimensions_hash),
            ).fetchone()
        if row is None:
            return None
        return {
            "metric_id": str(row["id"]),
            "run_id": str(row["run_id"]),
            "source_id": str(row["source_id"]),
            "definition_version": str(row["definition_version"]),
            "value": json.loads(str(row["value_json"])),
            "unit": None if row["unit"] is None else str(row["unit"]),
            "numerator": (
                None if row["numerator"] is None else float(row["numerator"])
            ),
            "denominator": (
                None if row["denominator"] is None else float(row["denominator"])
            ),
            "dimensions": json.loads(str(row["dimensions_json"])),
            "method_version": str(row["method_version"]),
            "run_method": str(row["run_method"]),
            "coverage": json.loads(str(row["coverage_json"])),
            "recorded_at": str(row["recorded_at"]),
        }

    def write_analytical_metric(
        self, request: AnalyticalMetricRequest, evidence: ImportEvidence
    ) -> dict[str, Any]:
        recorded_at = _now()
        dimensions_json = canonical_json(request.dimensions)
        dimensions_hash = sha256_bytes(dimensions_json.encode("utf-8"))
        source_id = stable_uuid("source", "analytical-result", evidence.object.digest)
        run_id = stable_uuid("analytical_run", request.idempotency_key)
        metric_id = stable_uuid(
            "metric", run_id, request.definition_version, dimensions_hash
        )
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_run = connection.execute(
                "SELECT id FROM analytical_run WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing_run is not None:
                return {
                    "evidence_digest": evidence.object.digest,
                    "fragment_id": evidence.fragment.id,
                    "idempotency_key": request.idempotency_key,
                    "metric_id": metric_id,
                    "replayed": True,
                    "run_id": str(existing_run["id"]),
                    "source_id": source_id,
                }
            connection.execute(
                "INSERT INTO source "
                "(id, natural_key, kind, locator, privacy_class, recorded_at) "
                "VALUES (?, ?, 'analytical-result', ?, ?, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (
                    source_id,
                    f"analytical-result:{evidence.object.digest}",
                    f"evidence:sha256:{evidence.object.digest}",
                    request.privacy,
                    recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_object "
                "(id, digest, byte_size, media_type, privacy_class, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (
                    evidence.object.id,
                    evidence.object.digest,
                    evidence.object.byte_size,
                    evidence.object.media_type,
                    evidence.object.privacy_class,
                    evidence.object.recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_fragment "
                "(id, evidence_object_id, locator_kind, locator_json, extractor_id, "
                "extractor_version, byte_size, digest, privacy_class, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (
                    evidence.fragment.id,
                    evidence.fragment.evidence_object_id,
                    evidence.fragment.locator_kind,
                    evidence.fragment.locator_json,
                    evidence.fragment.extractor_id,
                    evidence.fragment.extractor_version,
                    evidence.fragment.byte_size,
                    evidence.fragment.digest,
                    evidence.fragment.privacy_class,
                    evidence.fragment.recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO analytical_run "
                "(id, idempotency_key, batch_id, source_id, method, recorded_at) "
                "VALUES (?, ?, NULL, ?, ?, ?)",
                (
                    run_id,
                    request.idempotency_key,
                    source_id,
                    request.method,
                    recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO evidence_acquisition "
                "(id, evidence_object_id, source_id, run_id, privacy_class, "
                "retention_required, retain_until, method, review_status, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, 1, NULL, ?, 'unreviewed', ?)",
                (
                    stable_uuid("evidence_acquisition", evidence.object.id, run_id),
                    evidence.object.id,
                    source_id,
                    run_id,
                    request.privacy,
                    request.method,
                    recorded_at,
                ),
            )
            connection.execute(
                "INSERT INTO metric "
                "(id, run_id, definition_version, value_json, unit, numerator, "
                "denominator, dimensions_json, dimensions_hash, method_version, "
                "coverage_json, complete, invalidated, fragment_id, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    metric_id,
                    run_id,
                    request.definition_version,
                    canonical_json(request.value),
                    request.unit,
                    request.numerator,
                    request.denominator,
                    dimensions_json,
                    dimensions_hash,
                    request.method_version,
                    canonical_json(request.coverage),
                    int(request.complete),
                    evidence.fragment.id,
                    recorded_at,
                ),
            )
            return {
                "evidence_digest": evidence.object.digest,
                "fragment_id": evidence.fragment.id,
                "idempotency_key": request.idempotency_key,
                "metric_id": metric_id,
                "replayed": False,
                "run_id": run_id,
                "source_id": source_id,
            }

    def search_text(self, query: str, limit: int) -> dict[str, Any]:
        terms = re.findall(r"\w+", query.casefold(), flags=re.UNICODE)
        if not terms:
            raise ValueError("search query must contain a word or number")
        fts_query = " AND ".join(f'"{term}"' for term in terms)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT search_document.*, bm25(search_document_fts) AS rank,
                       node_attribute.value_json, node_attribute.json_type,
                       node_attribute.source_id, node_attribute.batch_id,
                       node_attribute.run_id, node_attribute.fragment_id,
                       node_attribute.updated_at
                FROM search_document_fts
                JOIN search_document
                    ON search_document.id = search_document_fts.document_id
                JOIN node_attribute
                    ON node_attribute.id = search_document.target_id
                WHERE search_document_fts MATCH ?
                  AND search_document.lifecycle = 'active'
                  AND node_attribute.searchable = 1
                ORDER BY rank, search_document.id
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
            eligible_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM node_attribute WHERE searchable = 1"
                ).fetchone()[0]
            )
            indexed_count = int(
                connection.execute(
                    """
                    SELECT COUNT(DISTINCT search_document.id)
                    FROM search_document
                    JOIN node_attribute
                        ON node_attribute.id = search_document.target_id
                    JOIN search_document_fts
                        ON search_document_fts.document_id = search_document.id
                    WHERE search_document.lifecycle = 'active'
                      AND node_attribute.searchable = 1
                    """
                ).fetchone()[0]
            )
        return {
            "results": [
                {
                    "document_id": str(row["id"]),
                    "target_kind": str(row["target_kind"]),
                    "target_id": str(row["target_id"]),
                    "content": str(row["content"]),
                    "content_hash": str(row["content_hash"]),
                    "privacy_class": str(row["privacy_class"]),
                    "rank": float(row["rank"]),
                    "value": json.loads(str(row["value_json"])),
                    "json_type": str(row["json_type"]),
                    "source_id": str(row["source_id"]),
                    "batch_id": None
                    if row["batch_id"] is None
                    else str(row["batch_id"]),
                    "run_id": None if row["run_id"] is None else str(row["run_id"]),
                    "fragment_id": None
                    if row["fragment_id"] is None
                    else str(row["fragment_id"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in rows
            ],
            "coverage": {
                "eligible_count": eligible_count,
                "indexed_count": indexed_count,
                "complete": indexed_count == eligible_count,
            },
        }

    def evidence_catalog(
        self, limit: int, digest: str | None = None
    ) -> tuple[list[dict[str, Any]], bool]:
        with self._connect() as connection:
            object_rows = connection.execute(
                "SELECT * FROM evidence_object WHERE (? IS NULL OR digest = ?) "
                "ORDER BY digest LIMIT ?",
                (digest, digest, limit + 1),
            ).fetchall()
            selected = object_rows[:limit]
            catalog: list[dict[str, Any]] = []
            for row in selected:
                object_id = str(row["id"])
                acquisitions = connection.execute(
                    "SELECT * FROM evidence_acquisition WHERE evidence_object_id = ? "
                    "ORDER BY recorded_at, id",
                    (object_id,),
                ).fetchall()
                fragments = connection.execute(
                    "SELECT * FROM evidence_fragment WHERE evidence_object_id = ? "
                    "ORDER BY recorded_at, id",
                    (object_id,),
                ).fetchall()
                locations = connection.execute(
                    "SELECT * FROM evidence_location WHERE evidence_object_id = ? "
                    "ORDER BY provider, root_id, object_key",
                    (object_id,),
                ).fetchall()
                verifications = connection.execute(
                    "SELECT * FROM evidence_verification "
                    "WHERE target_kind = 'object' AND target_id = ? "
                    "ORDER BY checked_at, id",
                    (object_id,),
                ).fetchall()
                retirement = connection.execute(
                    "SELECT * FROM evidence_retirement WHERE evidence_object_id = ?",
                    (object_id,),
                ).fetchone()
                catalog.append(
                    {
                        "object": dict(row),
                        "acquisitions": [dict(item) for item in acquisitions],
                        "fragments": [dict(item) for item in fragments],
                        "locations": [dict(item) for item in locations],
                        "verifications": [dict(item) for item in verifications],
                        "retirement": None if retirement is None else dict(retirement),
                    }
                )
        return catalog, len(object_rows) > limit

    def record_evidence_check(
        self,
        digest: str,
        *,
        availability: str,
        verification: str,
        byte_size: int | None,
        checked_at: str,
        method: str,
    ) -> dict[str, Any]:
        with self._write_connection() as connection:
            row = connection.execute(
                "SELECT id FROM evidence_object WHERE digest = ?", (digest,)
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"evidence object not found: {digest}")
            object_id = str(row["id"])
            location_id = stable_uuid(
                "evidence_location", object_id, "local-filesystem", "default"
            )
            object_key = f"objects/sha256/{digest[:2]}/{digest}"
            connection.execute(
                """
                INSERT INTO evidence_location (
                    id, evidence_object_id, provider, root_id, object_key,
                    availability, verified_at, recorded_at
                ) VALUES (?, ?, 'local-filesystem', 'default', ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    availability = excluded.availability,
                    verified_at = excluded.verified_at,
                    recorded_at = excluded.recorded_at
                """,
                (
                    location_id,
                    object_id,
                    object_key,
                    availability,
                    checked_at,
                    checked_at,
                ),
            )
            outcome = "missing" if availability == "missing" else verification
            verification_id = stable_uuid(
                "evidence_verification", object_id, checked_at, method
            )
            connection.execute(
                """
                INSERT INTO evidence_verification (
                    id, target_kind, target_id, digest, outcome, byte_size,
                    method, checked_at
                ) VALUES (?, 'object', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    verification_id,
                    object_id,
                    digest,
                    outcome,
                    byte_size,
                    method,
                    checked_at,
                ),
            )
        return {
            "availability": availability,
            "byte_size": byte_size,
            "digest": digest,
            "verification": verification,
        }

    def record_fragment_check(
        self,
        fragment_id: str,
        *,
        digest: str,
        outcome: str,
        byte_size: int | None,
        checked_at: str,
        method: str,
    ) -> None:
        with self._write_connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM evidence_fragment WHERE id = ?", (fragment_id,)
                ).fetchone()
                is None
            ):
                raise RecordNotFoundError(f"evidence fragment not found: {fragment_id}")
            verification_id = stable_uuid(
                "evidence_verification", fragment_id, checked_at, method
            )
            connection.execute(
                """
                INSERT INTO evidence_verification (
                    id, target_kind, target_id, digest, outcome, byte_size,
                    method, checked_at
                ) VALUES (?, 'fragment', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    verification_id,
                    fragment_id,
                    digest,
                    outcome,
                    byte_size,
                    method,
                    checked_at,
                ),
            )

    def record_artifact_check(
        self,
        target_kind: str,
        target_id: str,
        *,
        digest: str,
        outcome: str,
        byte_size: int | None,
        checked_at: str,
        method: str,
    ) -> None:
        if target_kind not in {"snapshot", "import"}:
            raise ValueError("artifact verification target must be snapshot or import")
        verification_id = stable_uuid(
            "evidence_verification", target_kind, target_id, checked_at, method
        )
        with self._write_connection() as connection:
            connection.execute(
                """
                INSERT INTO evidence_verification (
                    id, target_kind, target_id, digest, outcome, byte_size,
                    method, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    verification_id,
                    target_kind,
                    target_id,
                    digest,
                    outcome,
                    byte_size,
                    method,
                    checked_at,
                ),
            )

    def retention_report(self, as_of: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH acquisition_summary AS (
                    SELECT evidence_object_id,
                           SUM(CASE
                               WHEN retention_required = 1 OR retain_until > ?
                               THEN 1 ELSE 0 END
                           ) AS blocking_acquisitions,
                           COUNT(*) AS acquisition_count
                    FROM evidence_acquisition
                    GROUP BY evidence_object_id
                )
                SELECT evidence_object.*,
                       COALESCE(acquisition_summary.blocking_acquisitions, 0)
                           AS blocking_acquisitions,
                       COALESCE(acquisition_summary.acquisition_count, 0)
                           AS acquisition_count,
                       evidence_retirement.retired_at,
                       evidence_location.availability
                FROM evidence_object
                LEFT JOIN acquisition_summary
                    ON acquisition_summary.evidence_object_id = evidence_object.id
                LEFT JOIN evidence_retirement
                    ON evidence_retirement.evidence_object_id = evidence_object.id
                LEFT JOIN evidence_location
                    ON evidence_location.evidence_object_id = evidence_object.id
                   AND evidence_location.provider = 'local-filesystem'
                   AND evidence_location.root_id = 'default'
                ORDER BY evidence_object.digest
                """,
                (as_of,),
            ).fetchall()
        return [
            {
                "object_id": str(row["id"]),
                "digest": str(row["digest"]),
                "byte_size": int(row["byte_size"]),
                "privacy_class": str(row["privacy_class"]),
                "availability": str(row["availability"] or "missing"),
                "acquisition_count": int(row["acquisition_count"]),
                "blocking_acquisitions": int(row["blocking_acquisitions"]),
                "retention_state": (
                    "retired"
                    if row["retired_at"] is not None
                    else ("active" if int(row["blocking_acquisitions"]) else "expired")
                ),
            }
            for row in rows
        ]

    def record_retirement(
        self, digest: str, *, plan_id: str, reason: str, retired_at: str
    ) -> None:
        self.record_retirements(
            [digest],
            plan_id=plan_id,
            reason=reason,
            retired_at=retired_at,
        )

    def record_retirements(
        self,
        digests: list[str],
        *,
        plan_id: str,
        reason: str,
        retired_at: str,
    ) -> None:
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for digest in digests:
                row = connection.execute(
                    """
                    SELECT evidence_object.id,
                           evidence_retirement.plan_id AS existing_plan_id,
                           EXISTS (
                               SELECT 1 FROM evidence_acquisition
                               WHERE evidence_acquisition.evidence_object_id =
                                     evidence_object.id
                                 AND (
                                     evidence_acquisition.retention_required = 1
                                     OR evidence_acquisition.retain_until > ?
                                 )
                           ) AS blocked
                    FROM evidence_object
                    LEFT JOIN evidence_retirement
                        ON evidence_retirement.evidence_object_id = evidence_object.id
                    WHERE evidence_object.digest = ?
                    """,
                    (retired_at, digest),
                ).fetchone()
                if row is None:
                    raise RecordNotFoundError(f"evidence object not found: {digest}")
                if bool(row["blocked"]):
                    raise RetentionBlockedError(
                        f"active retention requirement blocks retirement: {digest}"
                    )
                if row["existing_plan_id"] is not None:
                    if str(row["existing_plan_id"]) == plan_id:
                        continue
                    raise RetentionBlockedError(
                        f"evidence object is already retired by another plan: {digest}"
                    )
                object_id = str(row["id"])
                connection.execute(
                    """
                    INSERT INTO evidence_retirement (
                        evidence_object_id, digest, plan_id, reason, retired_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (object_id, digest, plan_id, reason, retired_at),
                )
                connection.execute(
                    """
                    UPDATE evidence_location
                    SET availability = 'missing', verified_at = ?, recorded_at = ?
                    WHERE evidence_object_id = ?
                      AND provider = 'local-filesystem' AND root_id = 'default'
                    """,
                    (retired_at, retired_at, object_id),
                )

    def snapshot_records(self) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as connection:
            return {
                table: [
                    dict(row)
                    for row in connection.execute(
                        f"SELECT * FROM {table} "
                        f"ORDER BY {SNAPSHOT_ORDER.get(table, '1')}"
                    )
                ]
                for table in SNAPSHOT_TABLES
            }

    def import_snapshot_records(
        self, records: dict[str, list[dict[str, Any]]]
    ) -> dict[str, int]:
        if set(records) != set(SNAPSHOT_TABLES):
            raise SnapshotError("snapshot canonical table set does not match")
        counts: dict[str, int] = {}
        with self._write_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("PRAGMA defer_foreign_keys = ON")
            nonempty = [
                table
                for table in SNAPSHOT_TABLES
                if int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
            ]
            if nonempty:
                raise SnapshotError("snapshot import requires an empty canonical store")
            for table in SNAPSHOT_TABLES:
                rows = records[table]
                columns = tuple(
                    str(row["name"])
                    for row in connection.execute(f"PRAGMA table_info({table})")
                )
                placeholders = ", ".join("?" for _ in columns)
                statement = (
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({placeholders})"
                )
                for row in rows:
                    if set(row) != set(columns):
                        raise SnapshotError(
                            f"snapshot row columns do not match table {table}"
                        )
                    connection.execute(
                        statement,
                        tuple(row[column] for column in columns),
                    )
                counts[table] = len(rows)
            connection.execute("DELETE FROM search_document_fts")
            connection.execute(
                """
                INSERT INTO search_document_fts(document_id, content)
                SELECT id, content FROM search_document WHERE lifecycle = 'active'
                """
            )
        return counts

    def transfer_records(self) -> dict[str, list[dict[str, Any]]]:
        records = self.snapshot_records()
        records["node_attribute"] = [
            {
                key: value
                for key, value in row.items()
                if key not in {"sort_text_folded", "sort_text_exact", "sort_number"}
            }
            for row in records["node_attribute"]
        ]
        return records

    def import_transfer_records(
        self, records: dict[str, list[dict[str, Any]]]
    ) -> dict[str, int]:
        normalized = {
            table: [dict(row) for row in rows] for table, rows in records.items()
        }
        for row in normalized.get("node_attribute", []):
            folded, exact, number = _sort_values(json.loads(str(row["value_json"])))
            row["sort_text_folded"] = folded
            row["sort_text_exact"] = exact
            row["sort_number"] = number
        return self.import_snapshot_records(normalized)

    def integrity(self) -> dict[str, Any]:
        with self._connect() as connection:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            migration_rows = connection.execute(
                "SELECT version, checksum, target_fingerprint FROM schema_migration "
                "WHERE backend_profile = 'sqlite' ORDER BY version"
            ).fetchall()
        messages = [str(row[0]) for row in integrity_rows]
        return {
            "foreign_key_errors": len(foreign_key_rows),
            "integrity": messages,
            "ok": messages == ["ok"] and not foreign_key_rows,
            "schema_version": version,
            "migrations": [
                {
                    "version": int(row["version"]),
                    "checksum": str(row["checksum"]),
                    "target_fingerprint": str(row["target_fingerprint"]),
                }
                for row in migration_rows
            ],
        }

    def status(self) -> MemoryStoreStatus:
        if not self.database.is_file():
            return MemoryStoreStatus(
                backend="sqlite", initialized=False, schema_version=0
            )
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        expected_version = len(load_migration_manifest(self.migrations_directory))
        return MemoryStoreStatus(
            backend="sqlite",
            initialized=version == expected_version,
            schema_version=version,
        )

    def evidence_digests(self, limit: int) -> tuple[list[str], bool]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT digest FROM evidence_object ORDER BY digest LIMIT ?",
                (limit + 1,),
            ).fetchall()
        return [str(row["digest"]) for row in rows[:limit]], len(rows) > limit

    def put_embedding_profile(self, profile: EmbeddingProfileRecord) -> None:
        with self._write_connection() as connection:
            connection.execute(
                """
                INSERT INTO embedding_profile (
                    id, attribute_name, provider, model, dimensions,
                    preprocessing_version, similarity, privacy_ceiling,
                    contract_hash, status, last_error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    profile.id,
                    profile.attribute_name,
                    profile.provider,
                    profile.model,
                    profile.dimensions,
                    profile.preprocessing_version,
                    profile.similarity,
                    profile.privacy_ceiling,
                    profile.contract_hash,
                    profile.status,
                    profile.last_error,
                    profile.created_at,
                ),
            )

    def get_embedding_profile(self, profile_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM embedding_profile WHERE id = ?", (profile_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"embedding profile not found: {profile_id}")
        return dict(row)

    def set_embedding_profile_status(
        self, profile_id: str, status: str, last_error: str | None
    ) -> None:
        with self._write_connection() as connection:
            cursor = connection.execute(
                "UPDATE embedding_profile SET status = ?, last_error = ? WHERE id = ?",
                (status, last_error, profile_id),
            )
        if cursor.rowcount != 1:
            raise RecordNotFoundError(f"embedding profile not found: {profile_id}")

    def embedding_documents(self, profile_id: str) -> list[dict[str, Any]]:
        profile = self.get_embedding_profile(profile_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT search_document.*, node.namespace, node.type AS node_type,
                       node_attribute.attribute_name
                FROM search_document
                JOIN node_attribute ON node_attribute.id = search_document.target_id
                JOIN node ON node.id = node_attribute.node_id
                WHERE search_document.lifecycle = 'active'
                  AND search_document.target_kind = 'node_attribute'
                  AND node_attribute.searchable = 1
                  AND node_attribute.attribute_name = ?
                  AND search_document.privacy_class = 'public'
                  AND ? = 'public'
                  AND NOT EXISTS (
                      SELECT 1 FROM embedding_record
                      WHERE embedding_record.profile_id = ?
                        AND embedding_record.search_document_id = search_document.id
                        AND embedding_record.input_content_hash =
                            search_document.content_hash
                  )
                ORDER BY search_document.id
                """,
                (profile["attribute_name"], profile["privacy_ceiling"], profile_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def put_embedding_records(self, records: list[EmbeddingRecord]) -> None:
        with self._write_connection() as connection:
            connection.executemany(
                """
                INSERT INTO embedding_record (
                    id, search_document_id, profile_id, input_content_hash,
                    vector_blob, dimensions, response_model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(search_document_id, profile_id, input_content_hash)
                DO NOTHING
                """,
                [
                    (
                        record.id,
                        record.search_document_id,
                        record.profile_id,
                        record.input_content_hash,
                        record.vector_blob,
                        record.dimensions,
                        record.response_model,
                        record.created_at,
                    )
                    for record in records
                ],
            )

    def clear_embedding_records(self, profile_id: str) -> int:
        self.get_embedding_profile(profile_id)
        with self._write_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM embedding_record WHERE profile_id = ?", (profile_id,)
            )
        return cursor.rowcount

    def embedding_candidates(
        self,
        profile_id: str,
        *,
        namespace: str | None,
        node_type: str | None,
        privacy_ceiling: str | None,
    ) -> list[dict[str, Any]]:
        profile = self.get_embedding_profile(profile_id)
        effective_ceiling = privacy_ceiling or str(profile["privacy_ceiling"])
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT embedding_record.*, search_document.target_kind,
                       search_document.target_id, search_document.content,
                       search_document.content_hash,
                       search_document.privacy_class, node.namespace,
                       node.type AS node_type,
                       node_attribute.attribute_name,
                       node_attribute.value_json, node_attribute.json_type,
                       node_attribute.source_id, node_attribute.batch_id,
                       node_attribute.run_id, node_attribute.fragment_id,
                       node_attribute.updated_at
                FROM embedding_record
                JOIN search_document
                  ON search_document.id = embedding_record.search_document_id
                JOIN node_attribute ON node_attribute.id = search_document.target_id
                JOIN node ON node.id = node_attribute.node_id
                WHERE embedding_record.profile_id = ?
                  AND embedding_record.input_content_hash =
                      search_document.content_hash
                  AND embedding_record.dimensions = ?
                  AND embedding_record.response_model = ?
                  AND search_document.lifecycle = 'active'
                  AND search_document.target_kind = 'node_attribute'
                  AND node_attribute.searchable = 1
                  AND node_attribute.attribute_name = ?
                  AND (? IS NULL OR node.namespace = ?)
                  AND (? IS NULL OR node.type = ?)
                  AND search_document.privacy_class = 'public'
                  AND ? = 'public'
                ORDER BY search_document.id
                """,
                (
                    profile_id,
                    profile["dimensions"],
                    profile["model"],
                    profile["attribute_name"],
                    namespace,
                    namespace,
                    node_type,
                    node_type,
                    effective_ceiling,
                ),
            ).fetchall()
        return [dict(row) for row in rows]

    def embedding_coverage(self, profile_id: str) -> dict[str, int]:
        profile = self.get_embedding_profile(profile_id)
        parameters = (profile["attribute_name"], profile["privacy_ceiling"])
        with self._connect() as connection:
            eligible = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM search_document
                    JOIN node_attribute
                      ON node_attribute.id = search_document.target_id
                    WHERE search_document.lifecycle = 'active'
                      AND search_document.target_kind = 'node_attribute'
                      AND node_attribute.searchable = 1
                      AND node_attribute.attribute_name = ?
                      AND search_document.privacy_class = 'public'
                      AND ? = 'public'
                    """,
                    parameters,
                ).fetchone()[0]
            )
            indexed = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM embedding_record
                    JOIN search_document
                      ON search_document.id = embedding_record.search_document_id
                    JOIN node_attribute
                      ON node_attribute.id = search_document.target_id
                    WHERE embedding_record.profile_id = ?
                      AND embedding_record.input_content_hash =
                          search_document.content_hash
                      AND embedding_record.dimensions = ?
                      AND embedding_record.response_model = ?
                      AND search_document.lifecycle = 'active'
                      AND search_document.target_kind = 'node_attribute'
                      AND node_attribute.searchable = 1
                      AND node_attribute.attribute_name = ?
                      AND search_document.privacy_class = 'public'
                      AND ? = 'public'
                    """,
                    (
                        profile_id,
                        profile["dimensions"],
                        profile["model"],
                        profile["attribute_name"],
                        profile["privacy_ceiling"],
                    ),
                ).fetchone()[0]
            )
        return {"eligible_count": eligible, "indexed_count": indexed}

    def explain_attribute(self, attribute_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT node_attribute.*, node.namespace,
                       node.type AS node_type,
                       source.kind AS source_kind,
                       source.locator AS source_locator,
                       evidence_object.digest AS evidence_digest,
                       evidence_object.byte_size AS evidence_byte_size,
                       evidence_object.media_type AS evidence_media_type
                FROM node_attribute
                JOIN node ON node.id = node_attribute.node_id
                JOIN source ON source.id = node_attribute.source_id
                LEFT JOIN evidence_fragment
                  ON evidence_fragment.id = node_attribute.fragment_id
                LEFT JOIN evidence_object
                  ON evidence_object.id = evidence_fragment.evidence_object_id
                WHERE node_attribute.id = ?
                """,
                (attribute_id,),
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"attribute not found: {attribute_id}")
        return {
            "attribute": {
                "attribute_id": str(row["id"]),
                "attribute_name": str(row["attribute_name"]),
                "batch_id": (None if row["batch_id"] is None else str(row["batch_id"])),
                "fragment_id": (
                    None if row["fragment_id"] is None else str(row["fragment_id"])
                ),
                "json_type": str(row["json_type"]),
                "node_id": str(row["node_id"]),
                "privacy_class": str(row["privacy_class"]),
                "run_id": None if row["run_id"] is None else str(row["run_id"]),
                "searchable": bool(row["searchable"]),
                "source_id": str(row["source_id"]),
                "updated_at": str(row["updated_at"]),
                "value": json.loads(str(row["value_json"])),
            },
            "evidence": (
                None
                if row["evidence_digest"] is None
                else {
                    "byte_size": int(row["evidence_byte_size"]),
                    "digest": str(row["evidence_digest"]),
                    "media_type": str(row["evidence_media_type"]),
                }
            ),
            "node": {
                "id": str(row["node_id"]),
                "namespace": str(row["namespace"]),
                "type": str(row["node_type"]),
            },
            "source": {
                "id": str(row["source_id"]),
                "kind": str(row["source_kind"]),
                "locator": str(row["source_locator"]),
            },
        }

    def explain_relation(self, relation_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT relation.*,
                       source.kind AS source_kind,
                       source.locator AS source_locator,
                       evidence_object.digest AS evidence_digest,
                       evidence_object.byte_size AS evidence_byte_size,
                       evidence_object.media_type AS evidence_media_type
                FROM relation
                JOIN source ON source.id = relation.source_id
                LEFT JOIN evidence_fragment
                  ON evidence_fragment.id = relation.fragment_id
                LEFT JOIN evidence_object
                  ON evidence_object.id = evidence_fragment.evidence_object_id
                WHERE relation.id = ?
                """,
                (relation_id,),
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"relation not found: {relation_id}")
        return {
            "relation": {
                "active": bool(row["active"]),
                "batch_id": (None if row["batch_id"] is None else str(row["batch_id"])),
                "fragment_id": (
                    None if row["fragment_id"] is None else str(row["fragment_id"])
                ),
                "logical_key": str(row["logical_key"]),
                "privacy_class": str(row["privacy_class"]),
                "relation_id": str(row["id"]),
                "relation_type": str(row["type"]),
                "run_id": None if row["run_id"] is None else str(row["run_id"]),
                "source_id": str(row["source_id"]),
                "source_node_id": str(row["source_node_id"]),
                "target_node_id": str(row["target_node_id"]),
                "updated_at": str(row["updated_at"]),
            },
            "evidence": (
                None
                if row["evidence_digest"] is None
                else {
                    "byte_size": int(row["evidence_byte_size"]),
                    "digest": str(row["evidence_digest"]),
                    "media_type": str(row["evidence_media_type"]),
                }
            ),
            "source": {
                "id": str(row["source_id"]),
                "kind": str(row["source_kind"]),
                "locator": str(row["source_locator"]),
            },
        }

    def explain_metric(self, metric_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT metric.*, analytical_run.batch_id,
                       analytical_run.source_id,
                       analytical_run.method AS run_method,
                       analytical_run.recorded_at AS run_recorded_at,
                       source.kind AS source_kind,
                       source.locator AS source_locator,
                       evidence_object.digest AS evidence_digest,
                       evidence_object.byte_size AS evidence_byte_size,
                       evidence_object.media_type AS evidence_media_type
                FROM metric
                JOIN analytical_run ON analytical_run.id = metric.run_id
                JOIN source ON source.id = analytical_run.source_id
                LEFT JOIN evidence_fragment
                  ON evidence_fragment.id = metric.fragment_id
                LEFT JOIN evidence_object
                  ON evidence_object.id = evidence_fragment.evidence_object_id
                WHERE metric.id = ?
                """,
                (metric_id,),
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"metric not found: {metric_id}")
        return {
            "evidence": (
                None
                if row["evidence_digest"] is None
                else {
                    "byte_size": int(row["evidence_byte_size"]),
                    "digest": str(row["evidence_digest"]),
                    "media_type": str(row["evidence_media_type"]),
                }
            ),
            "metric": {
                "complete": bool(row["complete"]),
                "coverage": json.loads(str(row["coverage_json"])),
                "definition_version": str(row["definition_version"]),
                "denominator": (
                    None if row["denominator"] is None else float(row["denominator"])
                ),
                "dimensions": json.loads(str(row["dimensions_json"])),
                "fragment_id": (
                    None if row["fragment_id"] is None else str(row["fragment_id"])
                ),
                "invalidated": bool(row["invalidated"]),
                "method_version": str(row["method_version"]),
                "metric_id": str(row["id"]),
                "numerator": (
                    None if row["numerator"] is None else float(row["numerator"])
                ),
                "recorded_at": str(row["recorded_at"]),
                "run_id": str(row["run_id"]),
                "unit": None if row["unit"] is None else str(row["unit"]),
                "value": json.loads(str(row["value_json"])),
            },
            "run": {
                "batch_id": None if row["batch_id"] is None else str(row["batch_id"]),
                "id": str(row["run_id"]),
                "method": str(row["run_method"]),
                "recorded_at": str(row["run_recorded_at"]),
                "source_id": str(row["source_id"]),
            },
            "source": {
                "id": str(row["source_id"]),
                "kind": str(row["source_kind"]),
                "locator": str(row["source_locator"]),
            },
        }


class SqliteMemoryStore(SqlMemoryStore):
    pass
