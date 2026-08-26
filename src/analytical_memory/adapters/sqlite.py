from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from analytical_memory.canonical import canonical_json, canonical_text_key
from analytical_memory.domain import BatchPlan, StoredBatch
from analytical_memory.errors import RecordNotFoundError, StoreNotInitializedError
from analytical_memory.ports import MemoryStore


def default_migration_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "migrations"
        / "sqlite"
        / "001_initial.sql"
    )


def _fact_state(supports: int, contradicts: int) -> str:
    if supports and contradicts:
        return "contested"
    if supports:
        return "supported"
    if contradicts:
        return "contradicted"
    return "unasserted"


class SqliteMemoryStore(MemoryStore):
    def __init__(self, database: Path, migration_path: Path | None = None) -> None:
        self.database = database
        self.migration_path = migration_path or default_migration_path()

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
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version == 0:
                connection.executescript(
                    self.migration_path.read_text(encoding="utf-8")
                )
            elif version != 1:
                raise StoreNotInitializedError(
                    f"unsupported SQLite schema version: {version}"
                )

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
    def _insert_many(
        connection: sqlite3.Connection,
        table: str,
        columns: tuple[str, ...],
        records: Iterable[object],
    ) -> None:
        placeholders = ", ".join("?" for _ in columns)
        column_list = ", ".join(columns)
        sql = (
            f"INSERT INTO {table} ({column_list}) VALUES ({placeholders}) "
            "ON CONFLICT(id) DO NOTHING"
        )
        connection.executemany(
            sql,
            [
                tuple(getattr(record, column) for column in columns)
                for record in records
            ],
        )

    def apply(self, plan: BatchPlan) -> dict[str, Any]:
        result = plan.result()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO ingestion_batch "
                "(id, idempotency_key, input_hash, schema_fingerprint, "
                "result_json, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    plan.id,
                    plan.idempotency_key,
                    plan.input_hash,
                    plan.schema_fingerprint,
                    canonical_json(result),
                    plan.recorded_at,
                ),
            )
            self._insert_many(
                connection,
                "source",
                (
                    "id",
                    "natural_key",
                    "kind",
                    "locator",
                    "privacy_class",
                    "recorded_at",
                ),
                (plan.source,),
            )
            self._insert_many(
                connection,
                "analytical_run",
                (
                    "id",
                    "idempotency_key",
                    "batch_id",
                    "source_id",
                    "valid_from",
                    "valid_to",
                    "method",
                    "recorded_at",
                ),
                (plan.run,),
            )
            self._insert_many(
                connection,
                "node",
                (
                    "id",
                    "namespace",
                    "type",
                    "natural_key",
                    "display_label",
                    "privacy_class",
                    "recorded_at",
                ),
                plan.nodes,
            )
            self._insert_many(
                connection,
                "node_attribute",
                (
                    "id",
                    "node_id",
                    "name",
                    "cardinality",
                    "value_json",
                    "value_hash",
                    "privacy_class",
                    "recorded_at",
                ),
                plan.attributes,
            )
            self._insert_many(
                connection,
                "assertion",
                (
                    "id",
                    "attribute_id",
                    "stance",
                    "basis",
                    "confidence",
                    "review_status",
                    "valid_from",
                    "valid_to",
                    "recorded_at",
                    "method",
                    "source_id",
                    "run_id",
                    "supersedes_assertion_id",
                    "lifecycle",
                    "stable_key",
                ),
                plan.assertions,
            )
            self._insert_many(
                connection,
                "evidence_object",
                (
                    "id",
                    "digest",
                    "byte_size",
                    "media_type",
                    "privacy_class",
                    "recorded_at",
                ),
                (plan.evidence.object,),
            )
            self._insert_many(
                connection,
                "evidence_fragment",
                (
                    "id",
                    "evidence_object_id",
                    "locator_kind",
                    "locator_json",
                    "extractor_id",
                    "extractor_version",
                    "byte_size",
                    "digest",
                    "privacy_class",
                    "recorded_at",
                ),
                (plan.evidence.fragment,),
            )
            self._insert_many(
                connection,
                "evidence_binding",
                (
                    "id",
                    "assertion_id",
                    "fragment_id",
                    "role",
                    "confidence",
                    "review_status",
                    "recorded_at",
                ),
                plan.bindings,
            )
        return result

    def current_facts(self) -> list[dict[str, Any]]:
        sql = """
            WITH effective_assertion AS (
                SELECT assertion.*
                FROM assertion
                WHERE assertion.lifecycle = 'active'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assertion AS successor
                      WHERE successor.supersedes_assertion_id = assertion.id
                        AND successor.lifecycle = 'active'
                  )
            )
            SELECT
                node_attribute.id AS attribute_id,
                node.namespace,
                node.type AS node_type,
                node.natural_key,
                node_attribute.name AS attribute_name,
                node_attribute.value_json,
                node_attribute.privacy_class,
                SUM(CASE WHEN effective_assertion.stance = 'supports' THEN 1 ELSE 0 END)
                    AS supports,
                SUM(
                    CASE WHEN effective_assertion.stance = 'contradicts'
                    THEN 1 ELSE 0 END
                )
                    AS contradicts
            FROM node_attribute
            JOIN node ON node.id = node_attribute.node_id
            LEFT JOIN effective_assertion
                ON effective_assertion.attribute_id = node_attribute.id
            GROUP BY
                node_attribute.id,
                node.namespace,
                node.type,
                node.natural_key,
                node_attribute.name,
                node_attribute.value_json,
                node_attribute.privacy_class
        """
        with self._connect() as connection:
            rows = connection.execute(sql).fetchall()
        facts = [
            {
                "attribute_id": str(row["attribute_id"]),
                "namespace": str(row["namespace"]),
                "node_type": str(row["node_type"]),
                "natural_key": str(row["natural_key"]),
                "attribute_name": str(row["attribute_name"]),
                "value": json.loads(str(row["value_json"])),
                "state": _fact_state(int(row["supports"]), int(row["contradicts"])),
                "privacy_class": str(row["privacy_class"]),
            }
            for row in rows
        ]
        facts.sort(
            key=lambda item: (
                canonical_text_key(str(item["namespace"])),
                canonical_text_key(str(item["node_type"])),
                canonical_text_key(str(item["natural_key"])),
                canonical_text_key(str(item["attribute_name"])),
                str(item["attribute_id"]),
            )
        )
        return facts

    def explain_attribute(self, attribute_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            attribute = connection.execute(
                """
                SELECT node_attribute.*, node.namespace, node.type AS node_type,
                       node.natural_key
                FROM node_attribute
                JOIN node ON node.id = node_attribute.node_id
                WHERE node_attribute.id = ?
                """,
                (attribute_id,),
            ).fetchone()
            if attribute is None:
                raise RecordNotFoundError(f"attribute not found: {attribute_id}")
            assertion_rows = connection.execute(
                """
                SELECT assertion.*,
                       NOT EXISTS (
                           SELECT 1 FROM assertion AS successor
                           WHERE successor.supersedes_assertion_id = assertion.id
                             AND successor.lifecycle = 'active'
                       ) AS effective
                FROM assertion
                WHERE assertion.attribute_id = ?
                ORDER BY assertion.recorded_at, assertion.id
                """,
                (attribute_id,),
            ).fetchall()
            binding_rows = connection.execute(
                """
                SELECT evidence_binding.*, evidence_fragment.locator_kind,
                       evidence_fragment.locator_json,
                       evidence_fragment.extractor_id,
                       evidence_fragment.extractor_version,
                       evidence_object.digest AS object_digest,
                       evidence_object.byte_size AS object_byte_size,
                       evidence_object.media_type,
                       evidence_object.privacy_class AS object_privacy_class
                FROM evidence_binding
                JOIN evidence_fragment
                    ON evidence_fragment.id = evidence_binding.fragment_id
                JOIN evidence_object
                    ON evidence_object.id = evidence_fragment.evidence_object_id
                WHERE evidence_binding.assertion_id IN (
                    SELECT id FROM assertion WHERE attribute_id = ?
                )
                ORDER BY evidence_binding.assertion_id, evidence_binding.id
                """,
                (attribute_id,),
            ).fetchall()

        bindings_by_assertion: dict[str, list[dict[str, Any]]] = {}
        for row in binding_rows:
            assertion_id = str(row["assertion_id"])
            bindings_by_assertion.setdefault(assertion_id, []).append(
                {
                    "binding_id": str(row["id"]),
                    "role": str(row["role"]),
                    "fragment_id": str(row["fragment_id"]),
                    "locator_kind": str(row["locator_kind"]),
                    "locator": json.loads(str(row["locator_json"])),
                    "extractor": {
                        "id": str(row["extractor_id"]),
                        "version": str(row["extractor_version"]),
                    },
                    "object": {
                        "digest": str(row["object_digest"]),
                        "byte_size": int(row["object_byte_size"]),
                        "media_type": str(row["media_type"]),
                        "privacy_class": str(row["object_privacy_class"]),
                    },
                }
            )
        assertions = [
            {
                "assertion_id": str(row["id"]),
                "stance": str(row["stance"]),
                "basis": str(row["basis"]),
                "confidence": float(row["confidence"]),
                "review_status": str(row["review_status"]),
                "valid_from": str(row["valid_from"]),
                "valid_to": None if row["valid_to"] is None else str(row["valid_to"]),
                "recorded_at": str(row["recorded_at"]),
                "method": str(row["method"]),
                "source_id": str(row["source_id"]),
                "run_id": str(row["run_id"]),
                "supersedes_assertion_id": (
                    None
                    if row["supersedes_assertion_id"] is None
                    else str(row["supersedes_assertion_id"])
                ),
                "effective": bool(row["effective"]),
                "evidence": bindings_by_assertion.get(str(row["id"]), []),
            }
            for row in assertion_rows
        ]
        fact = next(
            item
            for item in self.current_facts()
            if item["attribute_id"] == attribute_id
        )
        return {
            "fact": fact,
            "node": {
                "id": str(attribute["node_id"]),
                "namespace": str(attribute["namespace"]),
                "type": str(attribute["node_type"]),
                "natural_key": str(attribute["natural_key"]),
            },
            "assertions": assertions,
        }

    def integrity(self) -> dict[str, Any]:
        with self._connect() as connection:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        messages = [str(row[0]) for row in integrity_rows]
        return {
            "foreign_key_errors": len(foreign_key_rows),
            "integrity": messages,
            "ok": messages == ["ok"] and not foreign_key_rows,
            "schema_version": version,
        }
