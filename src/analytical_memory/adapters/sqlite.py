from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from analytical_memory.adapters.sql_dialect import SqliteDialect
from analytical_memory.adapters.sql_store import (
    SNAPSHOT_TABLES,
    SqlMemoryStore,
    _sort_values,
)
from analytical_memory.domain import MemoryStoreStatus
from analytical_memory.errors import SnapshotError, StoreNotInitializedError
from analytical_memory.sqlite_migrations import (
    default_sqlite_migrations_directory,
    load_sqlite_migration_manifest,
    migrate_sqlite,
)


class SqliteMemoryStore(SqlMemoryStore):
    def __init__(
        self, database: Path, migrations_directory: Path | None = None
    ) -> None:
        super().__init__(SqliteDialect())
        self.database = database
        self.migrations_directory = (
            migrations_directory or default_sqlite_migrations_directory()
        )

    def _connect(self, *, require_initialized: bool = True) -> sqlite3.Connection:
        if require_initialized and not self.database.is_file():
            raise StoreNotInitializedError("memory store is not initialized")
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect(require_initialized=False)
        try:
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
        finally:
            connection.close()

    def search_text(self, query: str, limit: int) -> dict[str, Any]:
        terms = re.findall(r"\w+", query.casefold(), flags=re.UNICODE)
        if not terms:
            raise ValueError("search query must contain a word or number")
        fts_query = " AND ".join(f'"{term}"' for term in terms)
        with self._read_connection() as connection:
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
                  AND search_document.privacy_class = 'public'
                  AND node_attribute.searchable = 1
                ORDER BY rank, search_document.id
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
            eligible_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM node_attribute WHERE searchable = 1 "
                    "AND json_type = 'string' AND privacy_class = 'public'"
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
                      AND search_document.privacy_class = 'public'
                      AND node_attribute.searchable = 1
                      AND node_attribute.json_type = 'string'
                      AND node_attribute.privacy_class = 'public'
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
                    "batch_id": (
                        None if row["batch_id"] is None else str(row["batch_id"])
                    ),
                    "run_id": (
                        None if row["run_id"] is None else str(row["run_id"])
                    ),
                    "fragment_id": (
                        None
                        if row["fragment_id"] is None
                        else str(row["fragment_id"])
                    ),
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

    def integrity(self) -> dict[str, Any]:
        manifest = load_sqlite_migration_manifest(self.migrations_directory)
        with self._read_connection() as connection:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            actual_tables = {str(row["name"]) for row in table_rows}
            expected_tables = {
                *SNAPSHOT_TABLES,
                "embedding_profile",
                "embedding_record",
                "schema_migration",
                "search_document_fts",
            }
            missing_tables = sorted(expected_tables - actual_tables)
            if "schema_migration" in actual_tables:
                migration_rows = connection.execute(
                    "SELECT version, checksum, target_fingerprint "
                    "FROM schema_migration WHERE backend_profile = 'sqlite' "
                    "ORDER BY version"
                ).fetchall()
            else:
                migration_rows = []
            search_tables = {"search_document", "search_document_fts"}
            unavailable_search_tables = sorted(search_tables - actual_tables)
            if unavailable_search_tables:
                fts_missing = 0
                fts_extra = 0
            else:
                fts_missing = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM search_document LEFT JOIN "
                        "search_document_fts ON search_document_fts.document_id = "
                        "search_document.id WHERE search_document.lifecycle = "
                        "'active' AND search_document_fts.document_id IS NULL"
                    ).fetchone()[0]
                )
                fts_extra = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM search_document_fts LEFT JOIN "
                        "search_document ON search_document.id = "
                        "search_document_fts.document_id AND "
                        "search_document.lifecycle = 'active' "
                        "WHERE search_document.id IS NULL"
                    ).fetchone()[0]
                )
        messages = [str(row[0]) for row in integrity_rows]
        orphan_counts: dict[str, int] = {}
        for row in foreign_key_rows:
            key = f"{row['table']}:{row['fkid']}"
            orphan_counts[key] = orphan_counts.get(key, 0) + 1
        ledger_issues: list[str] = []
        if len(migration_rows) != len(manifest.migrations):
            ledger_issues.append("migration ledger length does not match")
        for row, definition in zip(
            migration_rows, manifest.migrations, strict=False
        ):
            if (
                int(row["version"]) != definition.version
                or str(row["checksum"]) != definition.checksum
                or str(row["target_fingerprint"]) != definition.target_fingerprint
            ):
                ledger_issues.append(
                    f"migration ledger mismatch at version {definition.version}"
                )
        checks = {
            "database": {"messages": messages, "ok": messages == ["ok"]},
            "foreign_keys": {
                "errors": len(foreign_key_rows),
                "ok": not foreign_key_rows,
                "orphan_counts": orphan_counts,
            },
            "migration_ledger": {"issues": ledger_issues, "ok": not ledger_issues},
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
                "invalid": [],
                "ok": True,
                "supported": False,
            },
        }
        return {
            "checks": checks,
            "foreign_key_errors": len(foreign_key_rows),
            "integrity": messages,
            "ok": (
                messages == ["ok"]
                and not foreign_key_rows
                and not ledger_issues
                and not missing_tables
                and not unavailable_search_tables
                and not fts_extra
                and not fts_missing
                and version == manifest.schema_version
            ),
            "physical_check": "sqlite_integrity_check",
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
        with self._read_connection() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        expected_version = load_sqlite_migration_manifest(
            self.migrations_directory
        ).schema_version
        return MemoryStoreStatus(
            backend="sqlite",
            initialized=version == expected_version,
            schema_version=version,
        )
