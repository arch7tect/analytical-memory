from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from analytical_memory.canonical import (
    canonical_json,
    canonical_text_key,
    sha256_bytes,
)
from analytical_memory.domain import BatchPlan, MemoryStoreStatus, StoredBatch
from analytical_memory.errors import (
    BatchValidationError,
    RecordNotFoundError,
    StoreNotInitializedError,
)
from analytical_memory.limits import MAX_EXPLANATION_ASSERTIONS, MAX_QUERY_RESULTS
from analytical_memory.migrations import default_migrations_directory, migrate_sqlite
from analytical_memory.ports import MemoryStore


def _fact_state(supports: int, contradicts: int) -> str:
    if supports and contradicts:
        return "contested"
    if supports:
        return "supported"
    if contradicts:
        return "contradicted"
    return "unasserted"


def _canonical_compare(left: str, right: str) -> int:
    left_key = canonical_text_key(left)
    right_key = canonical_text_key(right)
    return (left_key > right_key) - (left_key < right_key)


def _binding_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "binding_id": str(row["id"]),
        "role": str(row["role"]),
        "fragment_id": str(row["fragment_id"]),
        "fragment": {
            "digest": str(row["fragment_digest"]),
            "byte_size": int(row["fragment_byte_size"]),
            "privacy_class": str(row["fragment_privacy_class"]),
        },
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


class SqliteMemoryStore(MemoryStore):
    def __init__(
        self, database: Path, migrations_directory: Path | None = None
    ) -> None:
        self.database = database
        self.migrations_directory = (
            migrations_directory or default_migrations_directory()
        )

    def _connect(self, *, require_initialized: bool = True) -> sqlite3.Connection:
        if require_initialized and not self.database.is_file():
            raise StoreNotInitializedError("memory store is not initialized")
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.create_collation("canonical_text", _canonical_compare)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect(require_initialized=False) as connection:
            migrate_sqlite(connection, self.migrations_directory)

    @contextmanager
    def _write_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        except sqlite3.IntegrityError as exc:
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
        with self._write_connection() as connection:
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
                    "searchable",
                    "privacy_class",
                    "recorded_at",
                ),
                plan.attributes,
            )
            self._insert_many(
                connection,
                "relation",
                (
                    "id",
                    "source_node_id",
                    "type",
                    "target_node_id",
                    "logical_key",
                    "privacy_class",
                    "recorded_at",
                ),
                plan.relations,
            )
            self._insert_many(
                connection,
                "assertion",
                (
                    "id",
                    "target_kind",
                    "target_id",
                    "attribute_id",
                    "relation_id",
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
                    "stable_key_version",
                ),
                plan.assertions,
            )
            self._insert_many(
                connection,
                "metric",
                (
                    "id",
                    "run_id",
                    "definition_version",
                    "value_json",
                    "unit",
                    "numerator",
                    "denominator",
                    "dimensions_json",
                    "dimensions_hash",
                    "method_version",
                    "coverage_json",
                    "complete",
                    "invalidated",
                    "recorded_at",
                ),
                plan.metrics,
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
                    "target_kind",
                    "target_id",
                    "assertion_id",
                    "metric_id",
                    "fragment_id",
                    "role",
                    "confidence",
                    "review_status",
                    "recorded_at",
                ),
                plan.bindings,
            )
            self._insert_many(
                connection,
                "search_document",
                (
                    "id",
                    "target_kind",
                    "target_id",
                    "chunk_index",
                    "content",
                    "content_hash",
                    "extraction_version",
                    "privacy_class",
                    "lifecycle",
                    "recorded_at",
                ),
                plan.search_documents,
            )
            for document in plan.search_documents:
                connection.execute(
                    "DELETE FROM search_document_fts WHERE document_id = ?",
                    (document.id,),
                )
                connection.execute(
                    "INSERT INTO search_document_fts (document_id, content) "
                    "VALUES (?, ?)",
                    (document.id, document.content),
                )
        return result

    def _current_facts(self, attribute_id: str | None = None) -> list[dict[str, Any]]:
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
            WHERE (? IS NULL OR node_attribute.id = ?)
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
            rows = connection.execute(sql, (attribute_id, attribute_id)).fetchall()
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

    def current_facts(self) -> list[dict[str, Any]]:
        return self._current_facts()[:MAX_QUERY_RESULTS]

    def current_slots(self) -> list[dict[str, Any]]:
        facts = self._current_facts()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, node_id, cardinality FROM node_attribute"
            ).fetchall()
        metadata = {
            str(row["id"]): (str(row["node_id"]), str(row["cardinality"]))
            for row in rows
        }
        grouped: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = {}
        for fact in facts:
            node_id, cardinality = metadata[str(fact["attribute_id"])]
            key = (
                node_id,
                str(fact["namespace"]),
                str(fact["node_type"]),
                str(fact["natural_key"]),
                str(fact["attribute_name"]),
                cardinality,
            )
            grouped.setdefault(key, []).append(fact)

        slots: list[dict[str, Any]] = []
        for key, slot_facts in grouped.items():
            node_id, namespace, node_type, natural_key, name, cardinality = key
            candidates = [
                fact
                for fact in slot_facts
                if fact["state"] in {"supported", "contested"}
            ]
            current_value: Any = None
            if cardinality == "multi":
                status = "values" if candidates else "missing"
            elif not candidates:
                status = "missing"
            elif len(candidates) > 1:
                status = "conflict"
            elif candidates[0]["state"] == "contested":
                status = "contested"
            else:
                status = "current"
                current_value = candidates[0]["value"]
            slots.append(
                {
                    "node_id": node_id,
                    "namespace": namespace,
                    "node_type": node_type,
                    "natural_key": natural_key,
                    "attribute_name": name,
                    "cardinality": cardinality,
                    "status": status,
                    "current_value": current_value,
                    "candidates": candidates,
                }
            )
        slots.sort(
            key=lambda item: (
                canonical_text_key(str(item["namespace"])),
                canonical_text_key(str(item["node_type"])),
                canonical_text_key(str(item["natural_key"])),
                canonical_text_key(str(item["attribute_name"])),
                str(item["node_id"]),
            )
        )
        return slots[:MAX_QUERY_RESULTS]

    def _query_current_relations(
        self,
        *,
        frontier: list[str] | None = None,
        relation_types: list[str] | None = None,
        direction: str = "both",
        states: list[str] | None = None,
        exclude_relation_ids: list[str] | None = None,
        relation_id: str | None = None,
        limit: int = MAX_QUERY_RESULTS,
    ) -> tuple[list[dict[str, Any]], bool]:
        sql = """
            WITH effective_assertion AS (
                SELECT assertion.*
                FROM assertion
                WHERE assertion.lifecycle = 'active'
                  AND assertion.target_kind = 'relation'
                  AND NOT EXISTS (
                      SELECT 1 FROM assertion AS successor
                      WHERE successor.supersedes_assertion_id = assertion.id
                        AND successor.lifecycle = 'active'
                  )
            ),
            relation_counts AS (
                SELECT relation.*,
                       source.namespace AS source_namespace,
                       source.type AS source_type,
                       source.natural_key AS source_natural_key,
                       target.namespace AS target_namespace,
                       target.type AS target_type,
                       target.natural_key AS target_natural_key,
                       SUM(
                           CASE WHEN effective_assertion.stance = 'supports'
                           THEN 1 ELSE 0 END
                       ) AS supports,
                       SUM(
                           CASE WHEN effective_assertion.stance = 'contradicts'
                           THEN 1 ELSE 0 END
                       ) AS contradicts
                FROM relation
                JOIN node AS source ON source.id = relation.source_node_id
                JOIN node AS target ON target.id = relation.target_node_id
                LEFT JOIN effective_assertion
                    ON effective_assertion.relation_id = relation.id
                GROUP BY relation.id
            ),
            current_relation AS (
                SELECT relation_counts.*,
                       CASE
                           WHEN supports > 0 AND contradicts > 0 THEN 'contested'
                           WHEN supports > 0 THEN 'supported'
                           WHEN contradicts > 0 THEN 'contradicted'
                           ELSE 'unasserted'
                       END AS state
                FROM relation_counts
            )
            SELECT * FROM current_relation
            WHERE (? IS NULL OR id = ?)
              AND (
                  ? IS NULL
                  OR (
                      (? IN ('outbound', 'both') AND source_node_id IN (
                          SELECT value FROM json_each(?)
                      ))
                      OR
                      (? IN ('inbound', 'both') AND target_node_id IN (
                          SELECT value FROM json_each(?)
                      ))
                  )
              )
              AND (
                  ? = 0
                  OR type IN (SELECT value FROM json_each(?))
              )
              AND (
                  json_array_length(?) = 0
                  OR state IN (SELECT value FROM json_each(?))
              )
              AND id NOT IN (SELECT value FROM json_each(?))
            ORDER BY
                source_namespace COLLATE canonical_text,
                source_natural_key COLLATE canonical_text,
                type COLLATE canonical_text,
                target_namespace COLLATE canonical_text,
                target_natural_key COLLATE canonical_text,
                logical_key COLLATE canonical_text,
                id
            LIMIT ?
        """
        frontier_json = None if frontier is None else canonical_json(frontier)
        types_json = canonical_json(relation_types or [])
        types_filter_enabled = int(relation_types is not None)
        states_json = canonical_json(states or [])
        excluded_json = canonical_json(exclude_relation_ids or [])
        with self._connect() as connection:
            rows = connection.execute(
                sql,
                (
                    relation_id,
                    relation_id,
                    frontier_json,
                    direction,
                    frontier_json,
                    direction,
                    frontier_json,
                    types_filter_enabled,
                    types_json,
                    states_json,
                    states_json,
                    excluded_json,
                    limit + 1,
                ),
            ).fetchall()
        relations: list[dict[str, Any]] = [
            {
                "relation_id": str(row["id"]),
                "type": str(row["type"]),
                "logical_key": str(row["logical_key"]),
                "source": {
                    "id": str(row["source_node_id"]),
                    "namespace": str(row["source_namespace"]),
                    "type": str(row["source_type"]),
                    "natural_key": str(row["source_natural_key"]),
                },
                "target": {
                    "id": str(row["target_node_id"]),
                    "namespace": str(row["target_namespace"]),
                    "type": str(row["target_type"]),
                    "natural_key": str(row["target_natural_key"]),
                },
                "state": str(row["state"]),
                "privacy_class": str(row["privacy_class"]),
            }
            for row in rows
        ]
        return relations[:limit], len(relations) > limit

    def current_relations(self) -> list[dict[str, Any]]:
        relations, _ = self._query_current_relations()
        return relations

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
        stored_start = self.get_node(start_node_id)
        start = {
            key: stored_start[key] for key in ("id", "namespace", "type", "natural_key")
        }
        nodes: list[dict[str, Any]] = [{**start, "depth": 0}]
        edges: list[dict[str, Any]] = []
        visited_nodes = {start_node_id}
        visited_edges: set[str] = set()
        frontier = [start_node_id]
        truncated = False
        for depth in range(1, max_depth + 1):
            remaining_edges = limit - len(edges)
            if remaining_edges == 0:
                truncated = True
                break
            relations, query_truncated = self._query_current_relations(
                frontier=frontier,
                relation_types=relation_types,
                direction=direction,
                states=states,
                exclude_relation_ids=sorted(visited_edges),
                limit=remaining_edges,
            )
            next_frontier: list[str] = []
            for relation in relations:
                source_id = str(relation["source"]["id"])
                neighbor = (
                    relation["target"] if source_id in frontier else relation["source"]
                )
                neighbor_id = str(neighbor["id"])
                if neighbor_id not in visited_nodes and len(nodes) >= limit:
                    truncated = True
                    break
                edges.append({**relation, "depth": depth})
                visited_edges.add(str(relation["relation_id"]))
                if neighbor_id not in visited_nodes:
                    nodes.append({**neighbor, "depth": depth})
                    visited_nodes.add(neighbor_id)
                    next_frontier.append(neighbor_id)
            if query_truncated:
                truncated = True
            frontier = next_frontier
            if truncated or not frontier:
                break
        return {
            "query": "traverse-relations",
            "start_node_id": start_node_id,
            "direction": direction,
            "max_depth": max_depth,
            "states": states,
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
        }

    def get_node(self, node_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, namespace, type, natural_key, display_label, "
                "privacy_class FROM node WHERE id = ?",
                (node_id,),
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"node not found: {node_id}")
        return {
            "id": str(row["id"]),
            "namespace": str(row["namespace"]),
            "type": str(row["type"]),
            "natural_key": str(row["natural_key"]),
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

    def search_text(self, query: str, limit: int) -> dict[str, Any]:
        terms = re.findall(r"\w+", query.casefold(), flags=re.UNICODE)
        if not terms:
            raise ValueError("search query must contain a word or number")
        fts_query = " AND ".join(f'"{term}"' for term in terms)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT search_document.*, bm25(search_document_fts) AS rank
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
                }
                for row in rows
            ],
            "coverage": {
                "eligible_count": eligible_count,
                "indexed_count": indexed_count,
                "complete": indexed_count == eligible_count,
            },
        }

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
                       source.kind AS source_kind,
                       source.locator AS source_locator,
                       source.privacy_class AS source_privacy_class,
                       analytical_run.method AS run_method,
                       analytical_run.valid_from AS run_valid_from,
                       analytical_run.valid_to AS run_valid_to,
                       analytical_run.recorded_at AS run_recorded_at,
                       NOT EXISTS (
                           SELECT 1 FROM assertion AS successor
                           WHERE successor.supersedes_assertion_id = assertion.id
                             AND successor.lifecycle = 'active'
                       ) AND assertion.lifecycle = 'active' AS effective
                FROM assertion
                JOIN source ON source.id = assertion.source_id
                JOIN analytical_run ON analytical_run.id = assertion.run_id
                WHERE assertion.attribute_id = ?
                ORDER BY assertion.recorded_at, assertion.id
                LIMIT ?
                """,
                (attribute_id, MAX_EXPLANATION_ASSERTIONS),
            ).fetchall()
            assertion_ids = [str(row["id"]) for row in assertion_rows]
            if assertion_ids:
                placeholders = ", ".join("?" for _ in assertion_ids)
                binding_rows = connection.execute(
                    f"""
                SELECT evidence_binding.*, evidence_fragment.locator_kind,
                       evidence_fragment.locator_json,
                       evidence_fragment.extractor_id,
                       evidence_fragment.extractor_version,
                       evidence_fragment.digest AS fragment_digest,
                       evidence_fragment.byte_size AS fragment_byte_size,
                       evidence_fragment.privacy_class AS fragment_privacy_class,
                       evidence_object.digest AS object_digest,
                       evidence_object.byte_size AS object_byte_size,
                       evidence_object.media_type,
                       evidence_object.privacy_class AS object_privacy_class
                FROM evidence_binding
                JOIN evidence_fragment
                    ON evidence_fragment.id = evidence_binding.fragment_id
                JOIN evidence_object
                    ON evidence_object.id = evidence_fragment.evidence_object_id
                WHERE evidence_binding.assertion_id IN ({placeholders})
                ORDER BY evidence_binding.assertion_id, evidence_binding.id
                """,
                    assertion_ids,
                ).fetchall()
            else:
                binding_rows = []

        bindings_by_assertion: dict[str, list[dict[str, Any]]] = {}
        for row in binding_rows:
            assertion_id = str(row["assertion_id"])
            bindings_by_assertion.setdefault(assertion_id, []).append(
                _binding_summary(row)
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
                "source": {
                    "id": str(row["source_id"]),
                    "kind": str(row["source_kind"]),
                    "locator": str(row["source_locator"]),
                    "privacy_class": str(row["source_privacy_class"]),
                },
                "run": {
                    "id": str(row["run_id"]),
                    "method": str(row["run_method"]),
                    "valid_from": str(row["run_valid_from"]),
                    "valid_to": (
                        None
                        if row["run_valid_to"] is None
                        else str(row["run_valid_to"])
                    ),
                    "recorded_at": str(row["run_recorded_at"]),
                },
                "supersedes_assertion_id": (
                    None
                    if row["supersedes_assertion_id"] is None
                    else str(row["supersedes_assertion_id"])
                ),
                "effective": bool(row["effective"]),
                "lifecycle": str(row["lifecycle"]),
                "stable_key": str(row["stable_key"]),
                "stable_key_version": int(row["stable_key_version"]),
                "evidence": bindings_by_assertion.get(str(row["id"]), []),
            }
            for row in assertion_rows
        ]
        fact = next(
            item
            for item in self._current_facts(attribute_id)
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

    def explain_relation(self, relation_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            relation = connection.execute(
                """
                SELECT relation.*,
                       source.namespace AS source_namespace,
                       source.type AS source_type,
                       source.natural_key AS source_natural_key,
                       target.namespace AS target_namespace,
                       target.type AS target_type,
                       target.natural_key AS target_natural_key
                FROM relation
                JOIN node AS source ON source.id = relation.source_node_id
                JOIN node AS target ON target.id = relation.target_node_id
                WHERE relation.id = ?
                """,
                (relation_id,),
            ).fetchone()
            if relation is None:
                raise RecordNotFoundError(f"relation not found: {relation_id}")
            assertion_rows = connection.execute(
                """
                SELECT assertion.*,
                       source.kind AS source_kind,
                       source.locator AS source_locator,
                       source.privacy_class AS source_privacy_class,
                       analytical_run.method AS run_method,
                       analytical_run.valid_from AS run_valid_from,
                       analytical_run.valid_to AS run_valid_to,
                       analytical_run.recorded_at AS run_recorded_at,
                       NOT EXISTS (
                           SELECT 1 FROM assertion AS successor
                           WHERE successor.supersedes_assertion_id = assertion.id
                             AND successor.lifecycle = 'active'
                       ) AND assertion.lifecycle = 'active' AS effective
                FROM assertion
                JOIN source ON source.id = assertion.source_id
                JOIN analytical_run ON analytical_run.id = assertion.run_id
                WHERE assertion.target_kind = 'relation'
                  AND assertion.target_id = ?
                ORDER BY assertion.recorded_at, assertion.id
                LIMIT ?
                """,
                (relation_id, MAX_EXPLANATION_ASSERTIONS),
            ).fetchall()
            assertion_ids = [str(row["id"]) for row in assertion_rows]
            binding_rows: list[sqlite3.Row] = []
            if assertion_ids:
                placeholders = ", ".join("?" for _ in assertion_ids)
                binding_rows = connection.execute(
                    f"""
                    SELECT evidence_binding.*, evidence_fragment.locator_kind,
                           evidence_fragment.locator_json,
                           evidence_fragment.extractor_id,
                           evidence_fragment.extractor_version,
                           evidence_fragment.digest AS fragment_digest,
                           evidence_fragment.byte_size AS fragment_byte_size,
                           evidence_fragment.privacy_class AS fragment_privacy_class,
                           evidence_object.digest AS object_digest,
                           evidence_object.byte_size AS object_byte_size,
                           evidence_object.media_type,
                           evidence_object.privacy_class AS object_privacy_class
                    FROM evidence_binding
                    JOIN evidence_fragment
                        ON evidence_fragment.id = evidence_binding.fragment_id
                    JOIN evidence_object
                        ON evidence_object.id = evidence_fragment.evidence_object_id
                    WHERE evidence_binding.assertion_id IN ({placeholders})
                    ORDER BY evidence_binding.assertion_id, evidence_binding.id
                    """,
                    assertion_ids,
                ).fetchall()

        bindings_by_assertion: dict[str, list[dict[str, Any]]] = {}
        for row in binding_rows:
            assertion_id = str(row["assertion_id"])
            bindings_by_assertion.setdefault(assertion_id, []).append(
                _binding_summary(row)
            )
        assertions = [
            {
                "assertion_id": str(row["id"]),
                "stance": str(row["stance"]),
                "basis": str(row["basis"]),
                "confidence": float(row["confidence"]),
                "review_status": str(row["review_status"]),
                "valid_from": str(row["valid_from"]),
                "valid_to": (None if row["valid_to"] is None else str(row["valid_to"])),
                "recorded_at": str(row["recorded_at"]),
                "method": str(row["method"]),
                "source_id": str(row["source_id"]),
                "run_id": str(row["run_id"]),
                "source": {
                    "id": str(row["source_id"]),
                    "kind": str(row["source_kind"]),
                    "locator": str(row["source_locator"]),
                    "privacy_class": str(row["source_privacy_class"]),
                },
                "run": {
                    "id": str(row["run_id"]),
                    "method": str(row["run_method"]),
                    "valid_from": str(row["run_valid_from"]),
                    "valid_to": (
                        None
                        if row["run_valid_to"] is None
                        else str(row["run_valid_to"])
                    ),
                    "recorded_at": str(row["run_recorded_at"]),
                },
                "supersedes_assertion_id": (
                    None
                    if row["supersedes_assertion_id"] is None
                    else str(row["supersedes_assertion_id"])
                ),
                "effective": bool(row["effective"]),
                "lifecycle": str(row["lifecycle"]),
                "stable_key": str(row["stable_key"]),
                "stable_key_version": int(row["stable_key_version"]),
                "evidence": bindings_by_assertion.get(str(row["id"]), []),
            }
            for row in assertion_rows
        ]
        fact = next(
            item
            for item in self._query_current_relations(relation_id=relation_id, limit=1)[
                0
            ]
            if item["relation_id"] == relation_id
        )
        return {"fact": fact, "assertions": assertions}

    def explain_metric(self, metric_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT metric.*, analytical_run.source_id,
                       analytical_run.method AS run_method,
                       analytical_run.valid_from AS run_valid_from,
                       analytical_run.valid_to AS run_valid_to,
                       analytical_run.recorded_at AS run_recorded_at,
                       source.kind AS source_kind,
                       source.locator AS source_locator,
                       source.privacy_class AS source_privacy_class
                FROM metric
                JOIN analytical_run ON analytical_run.id = metric.run_id
                JOIN source ON source.id = analytical_run.source_id
                WHERE metric.id = ?
                """,
                (metric_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"metric not found: {metric_id}")
            binding_rows = connection.execute(
                """
                SELECT evidence_binding.*, evidence_fragment.locator_kind,
                       evidence_fragment.locator_json,
                       evidence_fragment.extractor_id,
                       evidence_fragment.extractor_version,
                       evidence_fragment.digest AS fragment_digest,
                       evidence_fragment.byte_size AS fragment_byte_size,
                       evidence_fragment.privacy_class AS fragment_privacy_class,
                       evidence_object.digest AS object_digest,
                       evidence_object.byte_size AS object_byte_size,
                       evidence_object.media_type,
                       evidence_object.privacy_class AS object_privacy_class
                FROM evidence_binding
                JOIN evidence_fragment
                    ON evidence_fragment.id = evidence_binding.fragment_id
                JOIN evidence_object
                    ON evidence_object.id = evidence_fragment.evidence_object_id
                WHERE evidence_binding.metric_id = ?
                ORDER BY evidence_binding.id
                """,
                (metric_id,),
            ).fetchall()
        return {
            "metric": {
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
                "complete": bool(row["complete"]),
                "invalidated": bool(row["invalidated"]),
                "recorded_at": str(row["recorded_at"]),
            },
            "evidence": [_binding_summary(binding) for binding in binding_rows],
            "source": {
                "id": str(row["source_id"]),
                "kind": str(row["source_kind"]),
                "locator": str(row["source_locator"]),
                "privacy_class": str(row["source_privacy_class"]),
            },
            "run": {
                "id": str(row["run_id"]),
                "method": str(row["run_method"]),
                "valid_from": str(row["run_valid_from"]),
                "valid_to": (
                    None if row["run_valid_to"] is None else str(row["run_valid_to"])
                ),
                "recorded_at": str(row["run_recorded_at"]),
            },
        }

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
        return MemoryStoreStatus(
            backend="sqlite",
            initialized=version == 2,
            schema_version=version,
        )

    def evidence_digests(self, limit: int) -> tuple[list[str], bool]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT digest FROM evidence_object ORDER BY digest LIMIT ?",
                (limit + 1,),
            ).fetchall()
        return [str(row["digest"]) for row in rows[:limit]], len(rows) > limit
