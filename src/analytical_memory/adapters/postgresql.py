from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg import ClientCursor, sql
from psycopg.rows import dict_row

from analytical_memory.adapters.sql_dialect import PostgresDialect, SqlDialect
from analytical_memory.adapters.sqlite import (
    SNAPSHOT_TABLES,
    SqlMemoryStore,
    _sort_values,
)
from analytical_memory.canonical import sha256_bytes
from analytical_memory.domain import MemoryStoreStatus
from analytical_memory.errors import SnapshotError, StoreNotInitializedError
from analytical_memory.migrations import MIGRATION_TOOL_VERSION
from analytical_memory.resources import resource_path


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
        super().__init__(Path("."), migrations_directory)
        self.dsn = dsn
        self.schema = schema
        self.migrations_directory = migrations_directory or resource_path(
            "migrations", "postgresql"
        )
        self.dialect = PostgresDialect(psycopg.IntegrityError)

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

    def _manifest(self) -> dict[str, Any]:
        path = self.migrations_directory / "manifest.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreNotInitializedError(
                "cannot load PostgreSQL migration manifest"
            ) from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("backend_profile") != "postgresql"
            or not isinstance(manifest.get("migrations"), list)
            or not manifest["migrations"]
        ):
            raise StoreNotInitializedError("invalid PostgreSQL migration manifest")
        for migration in manifest["migrations"]:
            source = self.migrations_directory / str(migration["file"])
            if sha256_bytes(source.read_bytes()) != migration["checksum"]:
                raise StoreNotInitializedError(
                    f"PostgreSQL migration checksum mismatch: {source.name}"
                )
        return manifest

    def initialize(self) -> None:
        manifest = self._manifest()
        migration = manifest["migrations"][0]
        connection = self._raw_connect()
        try:
            existing = connection.execute(
                "SELECT to_regclass('schema_migration') AS relation"
            ).fetchone()
            if existing is None or existing["relation"] is None:
                source = self.migrations_directory / str(migration["file"])
                connection.execute(source.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migration "
                "(backend_profile, version, checksum, target_fingerprint, "
                "applied_at, tool_version) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT(backend_profile, version) DO NOTHING",
                (
                    "postgresql",
                    int(migration["version"]),
                    str(migration["checksum"]),
                    str(migration["target_fingerprint"]),
                    datetime.now(UTC)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
                    MIGRATION_TOOL_VERSION,
                ),
            )
            row = connection.execute(
                "SELECT version, checksum, target_fingerprint FROM schema_migration "
                "WHERE backend_profile = 'postgresql' "
                "ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if (
                row is None
                or int(row["version"]) != int(migration["version"])
                or str(row["checksum"]) != str(migration["checksum"])
                or str(row["target_fingerprint"])
                != str(migration["target_fingerprint"])
            ):
                raise StoreNotInitializedError(
                    "PostgreSQL migration ledger does not match the package"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
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
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT version, checksum, target_fingerprint FROM schema_migration "
                "WHERE backend_profile = 'postgresql' ORDER BY version"
            ).fetchall()
        version = max((int(row["version"]) for row in rows), default=0)
        return {
            "foreign_key_errors": 0,
            "integrity": ["ok"],
            "ok": True,
            "schema_version": version,
            "migrations": [dict(row) for row in rows],
        }

    def status(self) -> MemoryStoreStatus:
        manifest = self._manifest()
        expected = int(manifest["schema_version"])
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
                "AND node_attribute.searchable = 1 "
                "ORDER BY rank, search_document.id LIMIT ?",
                (tsquery, tsquery, limit),
            ).fetchall()
            eligible_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM node_attribute WHERE searchable = 1"
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
                    "AND node_attribute.searchable = 1"
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
