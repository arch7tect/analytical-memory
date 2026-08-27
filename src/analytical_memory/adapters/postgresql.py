from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg import ClientCursor, sql
from psycopg.rows import dict_row

from analytical_memory.adapters.sql_dialect import PostgresDialect, SqlDialect
from analytical_memory.adapters.sql_store import (
    SNAPSHOT_TABLES,
    SqlMemoryStore,
    _sort_values,
)
from analytical_memory.domain import MemoryStoreStatus
from analytical_memory.errors import SnapshotError, StoreNotInitializedError
from analytical_memory.postgresql_migrations import (
    default_postgresql_migrations_directory,
    load_postgresql_migration_manifest,
    migrate_postgresql,
)


class HybridRow(dict[str, Any]):
    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class PostgresCursor:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    @staticmethod
    def _row(row: Any) -> HybridRow | None:
        if row is None:
            return None
        return HybridRow(row)

    def fetchone(self) -> HybridRow | None:
        return self._row(self.cursor.fetchone())

    def fetchall(self) -> list[HybridRow]:
        return [HybridRow(row) for row in self.cursor.fetchall()]

    def __iter__(self) -> Iterator[HybridRow]:
        return (HybridRow(row) for row in self.cursor)

    @property
    def rowcount(self) -> int:
        return int(self.cursor.rowcount)


class PostgresConnection:
    def __init__(self, connection: psycopg.Connection[Any], dialect: SqlDialect):
        self.connection = connection
        self.dialect = dialect

    def execute(
        self, statement: str, parameters: tuple[Any, ...] | list[Any] = ()
    ) -> PostgresCursor:
        cursor = self.connection.execute(self.dialect.rewrite(statement), parameters)
        return PostgresCursor(cursor)

    def executemany(self, statement: str, parameters: list[tuple[Any, ...]]) -> None:
        with self.connection.cursor() as cursor:
            cursor.executemany(self.dialect.rewrite(statement), parameters)

    def __enter__(self) -> PostgresConnection:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> Literal[False]:
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
        return False

    def close(self) -> None:
        self.connection.close()


class PostgresMemoryStore(SqlMemoryStore):
    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "public",
        migrations_directory: Path | None = None,
    ) -> None:
        super().__init__(PostgresDialect(psycopg.IntegrityError))
        self.dsn = dsn
        self.schema = schema
        self.migrations_directory = (
            migrations_directory or default_postgresql_migrations_directory()
        )

    def _raw_connect(self) -> psycopg.Connection[Any]:
        connection = psycopg.connect(
            self.dsn,
            row_factory=dict_row,
            cursor_factory=ClientCursor,
        )
        connection.execute(
            sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema))
        )
        return connection

    def _connect(self, *, require_initialized: bool = True) -> Any:
        connection = self._raw_connect()
        wrapped = PostgresConnection(connection, self.dialect)
        if require_initialized:
            try:
                row = wrapped.execute(
                    "SELECT to_regclass('schema_migration') AS relation"
                ).fetchone()
                if row is None or row["relation"] is None:
                    raise StoreNotInitializedError("memory store is not initialized")
            except Exception:
                connection.close()
                raise
        return wrapped

    def initialize(self) -> None:
        connection = self._raw_connect()
        try:
            migrate_postgresql(connection, self.migrations_directory)
        finally:
            connection.close()

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
                    str(row["column_name"])
                    for row in connection.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = ? AND table_name = ? "
                        "ORDER BY ordinal_position",
                        (self.schema, table),
                    )
                )
                placeholders = ", ".join("?" for _ in columns)
                statement = (
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({placeholders})"
                )
                for row in rows:
                    canonical_row = dict(row)
                    if table == "node_attribute":
                        folded, exact, number = _sort_values(
                            json.loads(str(canonical_row["value_json"]))
                        )
                        canonical_row["sort_text_folded"] = folded
                        canonical_row["sort_text_exact"] = exact
                        canonical_row["sort_number"] = number
                    if set(canonical_row) != set(columns):
                        raise SnapshotError(
                            f"snapshot row columns do not match table {table}"
                        )
                    connection.execute(
                        statement,
                        tuple(canonical_row[column] for column in columns),
                    )
                counts[table] = len(rows)
            connection.execute("DELETE FROM search_document_fts")
            connection.execute(
                "INSERT INTO search_document_fts(document_id, content) "
                "SELECT id, content FROM search_document WHERE lifecycle = 'active'"
            )
        return counts

    def integrity(self) -> dict[str, Any]:
        manifest = load_postgresql_migration_manifest(self.migrations_directory)
        connection = self._raw_connect()
        try:
            table_rows = connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                (self.schema,),
            ).fetchall()
            actual_tables = {str(row["table_name"]) for row in table_rows}
            expected_tables = {
                *SNAPSHOT_TABLES,
                "embedding_profile",
                "embedding_record",
                "schema_migration",
                "search_document_fts",
            }
            missing_tables = sorted(expected_tables - actual_tables)
            if "schema_migration" in actual_tables:
                rows = list(
                    connection.execute(
                        "SELECT version, checksum, target_fingerprint "
                        "FROM schema_migration WHERE backend_profile = 'postgresql' "
                        "ORDER BY version"
                    ).fetchall()
                )
            else:
                rows = []
            ledger_issues: list[str] = []
            if len(rows) != len(manifest.migrations):
                ledger_issues.append("migration ledger length does not match")
            for row, definition in zip(rows, manifest.migrations, strict=False):
                if (
                    int(row["version"]) != definition.version
                    or str(row["checksum"]) != definition.checksum
                    or str(row["target_fingerprint"])
                    != definition.target_fingerprint
                ):
                    ledger_issues.append(
                        f"migration ledger mismatch at version {definition.version}"
                    )

            unvalidated = [
                {
                    "constraint": str(row["constraint_name"]),
                    "table": str(row["table_name"]),
                }
                for row in connection.execute(
                    "SELECT constraint_row.conname AS constraint_name, "
                    "table_row.relname AS table_name FROM pg_constraint "
                    "AS constraint_row JOIN pg_class AS table_row "
                    "ON table_row.oid = constraint_row.conrelid "
                    "JOIN pg_namespace AS namespace_row "
                    "ON namespace_row.oid = table_row.relnamespace "
                    "WHERE namespace_row.nspname = %s "
                    "AND NOT constraint_row.convalidated "
                    "ORDER BY table_row.relname, constraint_row.conname",
                    (self.schema,),
                ).fetchall()
            ]

            foreign_key_rows = connection.execute(
                "SELECT constraint_row.conname AS constraint_name, "
                "child_table.relname AS child_table, "
                "child_column.attname AS child_column, "
                "parent_table.relname AS parent_table, "
                "parent_column.attname AS parent_column, "
                "child_key.ordinality AS position "
                "FROM pg_constraint AS constraint_row "
                "JOIN pg_class AS child_table "
                "ON child_table.oid = constraint_row.conrelid "
                "JOIN pg_class AS parent_table "
                "ON parent_table.oid = constraint_row.confrelid "
                "JOIN pg_namespace AS namespace_row "
                "ON namespace_row.oid = child_table.relnamespace "
                "JOIN unnest(constraint_row.conkey) WITH ORDINALITY "
                "AS child_key(attribute_number, ordinality) ON TRUE "
                "JOIN unnest(constraint_row.confkey) WITH ORDINALITY "
                "AS parent_key(attribute_number, ordinality) "
                "ON parent_key.ordinality = child_key.ordinality "
                "JOIN pg_attribute AS child_column "
                "ON child_column.attrelid = child_table.oid "
                "AND child_column.attnum = child_key.attribute_number "
                "JOIN pg_attribute AS parent_column "
                "ON parent_column.attrelid = parent_table.oid "
                "AND parent_column.attnum = parent_key.attribute_number "
                "WHERE constraint_row.contype = 'f' "
                "AND namespace_row.nspname = %s "
                "ORDER BY constraint_row.conname, child_key.ordinality",
                (self.schema,),
            ).fetchall()
            foreign_keys: dict[str, dict[str, Any]] = {}
            for row in foreign_key_rows:
                item = foreign_keys.setdefault(
                    str(row["constraint_name"]),
                    {
                        "child_table": str(row["child_table"]),
                        "parent_table": str(row["parent_table"]),
                        "columns": [],
                    },
                )
                item["columns"].append(
                    (str(row["child_column"]), str(row["parent_column"]))
                )
            orphan_counts: dict[str, int] = {}
            for name, item in foreign_keys.items():
                columns = item["columns"]
                join_conditions = sql.SQL(" AND ").join(
                    sql.SQL("child.{} = parent.{}").format(
                        sql.Identifier(child), sql.Identifier(parent)
                    )
                    for child, parent in columns
                )
                non_null = sql.SQL(" AND ").join(
                    sql.SQL("child.{} IS NOT NULL").format(sql.Identifier(child))
                    for child, _ in columns
                )
                statement = sql.SQL(
                    "SELECT COUNT(*) AS count FROM {} AS child LEFT JOIN {} "
                    "AS parent ON {} WHERE {} AND parent.{} IS NULL"
                ).format(
                    sql.Identifier(self.schema, item["child_table"]),
                    sql.Identifier(self.schema, item["parent_table"]),
                    join_conditions,
                    non_null,
                    sql.Identifier(columns[0][1]),
                )
                result = connection.execute(statement).fetchone()
                count = 0 if result is None else int(result["count"])
                if count:
                    orphan_counts[name] = count

            search_tables = {"search_document", "search_document_fts"}
            unavailable_search_tables = sorted(search_tables - actual_tables)
            if unavailable_search_tables:
                fts_missing = 0
                fts_extra = 0
            else:
                missing_row = connection.execute(
                    "SELECT COUNT(*) AS count FROM search_document "
                    "LEFT JOIN search_document_fts ON "
                    "search_document_fts.document_id = search_document.id "
                    "WHERE search_document.lifecycle = 'active' "
                    "AND search_document_fts.document_id IS NULL"
                ).fetchone()
                extra_row = connection.execute(
                    "SELECT COUNT(*) AS count FROM search_document_fts "
                    "LEFT JOIN search_document ON search_document.id = "
                    "search_document_fts.document_id AND "
                    "search_document.lifecycle = 'active' "
                    "WHERE search_document.id IS NULL"
                ).fetchone()
                fts_missing = (
                    0 if missing_row is None else int(missing_row["count"])
                )
                fts_extra = 0 if extra_row is None else int(extra_row["count"])
        finally:
            connection.close()

        version = max((int(row["version"]) for row in rows), default=0)
        checks = {
            "database": {
                "messages": ["physical check unsupported"],
                "ok": True,
                "supported": False,
            },
            "foreign_keys": {
                "errors": sum(orphan_counts.values()),
                "ok": not orphan_counts,
                "orphan_counts": orphan_counts,
            },
            "migration_ledger": {"ok": not ledger_issues, "issues": ledger_issues},
            "search_index": {
                "extra_rows": fts_extra,
                "missing_rows": fts_missing,
                "ok": (
                    not unavailable_search_tables
                    and not fts_extra
                    and not fts_missing
                ),
                "unavailable_tables": unavailable_search_tables,
            },
            "schema_version": {
                "actual": version,
                "expected": manifest.schema_version,
                "ok": version == manifest.schema_version,
            },
            "tables": {"missing": missing_tables, "ok": not missing_tables},
            "validated_constraints": {
                "invalid": unvalidated,
                "ok": not unvalidated,
            },
        }
        ok = (
            not orphan_counts
            and not ledger_issues
            and not unavailable_search_tables
            and not fts_extra
            and not fts_missing
            and not missing_tables
            and not unvalidated
            and version == manifest.schema_version
        )
        return {
            "checks": checks,
            "foreign_key_errors": sum(orphan_counts.values()),
            "integrity": ["ok"] if ok else ["failed"],
            "migrations": [dict(row) for row in rows],
            "ok": ok,
            "physical_check": "unsupported",
            "schema_version": version,
        }

    def status(self) -> MemoryStoreStatus:
        manifest = load_postgresql_migration_manifest(self.migrations_directory)
        expected = manifest.schema_version
        try:
            with self._connect(require_initialized=False) as connection:
                relation = connection.execute(
                    "SELECT to_regclass('schema_migration') AS relation"
                ).fetchone()
                if relation is None or relation["relation"] is None:
                    return MemoryStoreStatus(
                        backend="postgresql", initialized=False, schema_version=0
                    )
                row = connection.execute(
                    "SELECT MAX(version) AS version FROM schema_migration "
                    "WHERE backend_profile = 'postgresql'"
                ).fetchone()
        except psycopg.Error:
            return MemoryStoreStatus(
                backend="postgresql", initialized=False, schema_version=0
            )
        version = 0 if row is None or row["version"] is None else int(row["version"])
        return MemoryStoreStatus(
            backend="postgresql",
            initialized=version == expected,
            schema_version=version,
        )

    def search_text(self, query: str, limit: int) -> dict[str, Any]:
        terms = re.findall(r"\w+", query.casefold(), flags=re.UNICODE)
        if not terms:
            raise ValueError("search query must contain a word or number")
        tsquery = " & ".join(terms)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT search_document.*, "
                "-ts_rank_cd(search_document_fts.content_tsv, "
                "to_tsquery('simple', ?)) AS rank, "
                "node_attribute.value_json, node_attribute.json_type, "
                "node_attribute.source_id, node_attribute.batch_id, "
                "node_attribute.run_id, node_attribute.fragment_id, "
                "node_attribute.updated_at "
                "FROM search_document_fts "
                "JOIN search_document ON search_document.id = "
                "search_document_fts.document_id "
                "JOIN node_attribute ON node_attribute.id = search_document.target_id "
                "WHERE search_document_fts.content_tsv @@ to_tsquery('simple', ?) "
                "AND search_document.lifecycle = 'active' "
                "AND search_document.privacy_class = 'public' "
                "AND node_attribute.searchable = 1 "
                "ORDER BY rank, search_document.id LIMIT ?",
                (tsquery, tsquery, limit),
            ).fetchall()
            eligible_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM node_attribute WHERE searchable = 1 "
                    "AND json_type = 'string' AND privacy_class = 'public'"
                ).fetchone()[0]
            )
            indexed_count = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT search_document.id) "
                    "FROM search_document "
                    "JOIN node_attribute ON node_attribute.id = "
                    "search_document.target_id "
                    "JOIN search_document_fts ON search_document_fts.document_id = "
                    "search_document.id WHERE search_document.lifecycle = 'active' "
                    "AND search_document.privacy_class = 'public' "
                    "AND node_attribute.searchable = 1 "
                    "AND node_attribute.json_type = 'string' "
                    "AND node_attribute.privacy_class = 'public'"
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
                    "batch_id": row["batch_id"],
                    "run_id": row["run_id"],
                    "fragment_id": row["fragment_id"],
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
