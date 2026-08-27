from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from analytical_memory.errors import StoreNotInitializedError
from analytical_memory.migrations import (
    MIGRATION_TOOL_VERSION,
    MigrationDefinition,
    MigrationManifest,
    load_migration_manifest,
)
from analytical_memory.resources import resource_path


def default_postgresql_migrations_directory() -> Path:
    return resource_path("migrations", "postgresql")


def load_postgresql_migration_manifest(directory: Path) -> MigrationManifest:
    return load_migration_manifest(directory, backend_profile="postgresql")


def _validate_ledger(
    rows: list[Any], definitions: tuple[MigrationDefinition, ...]
) -> None:
    if len(rows) > len(definitions):
        raise StoreNotInitializedError(
            "PostgreSQL migration ledger does not match the package"
        )
    for row, definition in zip(rows, definitions, strict=False):
        if (
            int(row["version"]) != definition.version
            or str(row["checksum"]) != definition.checksum
            or str(row["target_fingerprint"]) != definition.target_fingerprint
        ):
            raise StoreNotInitializedError(
                "PostgreSQL migration ledger does not match the package"
            )


def migrate_postgresql(
    connection: psycopg.Connection[Any], directory: Path | None = None
) -> int:
    migration_directory = directory or default_postgresql_migrations_directory()
    manifest = load_postgresql_migration_manifest(migration_directory)
    try:
        relation = connection.execute(
            "SELECT to_regclass('schema_migration') AS relation"
        ).fetchone()
        initialized = relation is not None and relation["relation"] is not None
        rows = (
            list(
                connection.execute(
                    "SELECT version, checksum, target_fingerprint "
                    "FROM schema_migration WHERE backend_profile = 'postgresql' "
                    "ORDER BY version"
                ).fetchall()
            )
            if initialized
            else []
        )
        if initialized and not rows:
            raise StoreNotInitializedError(
                "PostgreSQL migration ledger does not match the package"
            )
        _validate_ledger(rows, manifest.migrations)
        for definition in manifest.migrations[len(rows) :]:
            source = migration_directory / definition.file
            try:
                connection.execute(source.read_text(encoding="utf-8"))
            except (OSError, psycopg.Error) as exc:
                raise StoreNotInitializedError(
                    f"PostgreSQL migration failed: {definition.file}"
                ) from exc
            connection.execute(
                "INSERT INTO schema_migration "
                "(backend_profile, version, checksum, target_fingerprint, "
                "applied_at, tool_version) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    "postgresql",
                    definition.version,
                    definition.checksum,
                    definition.target_fingerprint,
                    datetime.now(UTC)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
                    MIGRATION_TOOL_VERSION,
                ),
            )
        final_rows = list(
            connection.execute(
                "SELECT version, checksum, target_fingerprint "
                "FROM schema_migration WHERE backend_profile = 'postgresql' "
                "ORDER BY version"
            ).fetchall()
        )
        _validate_ledger(final_rows, manifest.migrations)
        if len(final_rows) != len(manifest.migrations):
            raise StoreNotInitializedError("PostgreSQL migration ledger is incomplete")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return manifest.schema_version
