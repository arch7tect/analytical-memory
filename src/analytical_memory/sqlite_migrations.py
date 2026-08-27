from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from analytical_memory.errors import StoreNotInitializedError
from analytical_memory.migrations import (
    MIGRATION_TOOL_VERSION,
    MigrationDefinition,
    MigrationManifest,
    load_migration_manifest,
)
from analytical_memory.resources import resource_path


def default_sqlite_migrations_directory() -> Path:
    return resource_path("migrations", "sqlite")


def load_sqlite_migration_manifest(directory: Path) -> MigrationManifest:
    manifest = load_migration_manifest(directory, backend_profile="sqlite")
    if manifest.migrations[0].version != 1:
        raise StoreNotInitializedError("SQLite migrations must start at version 1")
    return manifest


def _record_ledger(
    connection: sqlite3.Connection,
    definitions: tuple[MigrationDefinition, ...],
    current_version: int,
) -> None:
    applied_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    with connection:
        for definition in definitions:
            if definition.version > current_version:
                break
            connection.execute(
                "INSERT INTO schema_migration "
                "(backend_profile, version, checksum, target_fingerprint, "
                "applied_at, tool_version) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(backend_profile, version) DO NOTHING",
                (
                    "sqlite",
                    definition.version,
                    definition.checksum,
                    definition.target_fingerprint,
                    applied_at,
                    MIGRATION_TOOL_VERSION,
                ),
            )
        rows = connection.execute(
            "SELECT version, checksum, target_fingerprint FROM schema_migration "
            "WHERE backend_profile = 'sqlite' ORDER BY version"
        ).fetchall()
    expected = [item for item in definitions if item.version <= current_version]
    if len(rows) != len(expected):
        raise StoreNotInitializedError("SQLite migration ledger is incomplete")
    for row, definition in zip(rows, expected, strict=True):
        if (
            int(row["version"]) != definition.version
            or str(row["checksum"]) != definition.checksum
            or str(row["target_fingerprint"]) != definition.target_fingerprint
        ):
            raise StoreNotInitializedError(
                f"SQLite migration ledger mismatch at version {definition.version}"
            )


def migrate_sqlite(
    connection: sqlite3.Connection, directory: Path | None = None
) -> int:
    migration_directory = directory or default_sqlite_migrations_directory()
    manifest = load_sqlite_migration_manifest(migration_directory)
    current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current_version > manifest.schema_version:
        raise StoreNotInitializedError(
            f"unsupported SQLite schema version: {current_version}"
        )
    for definition in manifest.migrations:
        if definition.version <= current_version:
            continue
        source = migration_directory / definition.file
        sql = source.read_text(encoding="utf-8")
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(f"BEGIN IMMEDIATE;\n{sql}")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise sqlite3.IntegrityError(
                    f"migration created {len(violations)} foreign-key violations"
                )
            connection.commit()
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.rollback()
            raise StoreNotInitializedError(
                f"SQLite migration failed: {definition.file}"
            ) from exc
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version != definition.version:
            raise StoreNotInitializedError(
                f"migration {definition.file} did not set user_version"
            )
    if current_version >= 2:
        _record_ledger(connection, manifest.migrations, current_version)
    return current_version
