from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from analytical_memory.canonical import sha256_bytes
from analytical_memory.errors import StoreNotInitializedError

MIGRATION_TOOL_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class MigrationDefinition:
    version: int
    file: str
    checksum: str
    target_fingerprint: str


def default_migrations_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations" / "sqlite"


def load_migration_manifest(directory: Path) -> tuple[MigrationDefinition, ...]:
    manifest_path = directory / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreNotInitializedError("cannot load SQLite migration manifest") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("migrations"), list):
        raise StoreNotInitializedError("invalid SQLite migration manifest")
    definitions: list[MigrationDefinition] = []
    for raw in payload["migrations"]:
        if not isinstance(raw, dict):
            raise StoreNotInitializedError("invalid SQLite migration entry")
        definition = MigrationDefinition(
            version=int(raw["version"]),
            file=str(raw["file"]),
            checksum=str(raw["checksum"]),
            target_fingerprint=str(raw["target_fingerprint"]),
        )
        source = directory / definition.file
        try:
            actual = sha256_bytes(source.read_bytes())
        except OSError as exc:
            raise StoreNotInitializedError(
                f"cannot read SQLite migration {definition.file}"
            ) from exc
        if actual != definition.checksum:
            raise StoreNotInitializedError(
                f"SQLite migration checksum mismatch: {definition.file}"
            )
        definitions.append(definition)
    versions = [item.version for item in definitions]
    if versions != list(range(1, len(definitions) + 1)):
        raise StoreNotInitializedError(
            "SQLite migrations must be contiguous and ordered"
        )
    return tuple(definitions)


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
    migration_directory = directory or default_migrations_directory()
    definitions = load_migration_manifest(migration_directory)
    current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current_version > len(definitions):
        raise StoreNotInitializedError(
            f"unsupported SQLite schema version: {current_version}"
        )
    for definition in definitions:
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
        _record_ledger(connection, definitions, current_version)
    return current_version
