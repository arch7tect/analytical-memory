from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.canonical import sha256_bytes
from analytical_memory.errors import StoreNotInitializedError

from .conftest import REPOSITORY_ROOT


def test_fresh_database_reaches_m5_schema(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    store = SqliteMemoryStore(database)

    store.initialize()

    integrity = store.integrity()
    assert integrity["schema_version"] == 5
    assert [item["version"] for item in integrity["migrations"]] == [1, 2, 3, 4, 5]
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"entity_declaration", "observed_field", "ontology_declaration"} <= tables
    assert "assertion" not in tables
    assert "evidence_binding" not in tables


def test_m5_clean_break_reinitializes_legacy_current_tables(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    migrations = REPOSITORY_ROOT / "migrations" / "sqlite"
    with sqlite3.connect(database) as connection:
        for version in range(1, 5):
            name = next(migrations.glob(f"{version:03d}_*.sql"))
            connection.executescript(name.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO node VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy",
                "legacy",
                "Item",
                "legacy-key",
                None,
                "public",
                "2000-01-01T00:00:00Z",
            ),
        )

    SqliteMemoryStore(database).initialize()

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM node").fetchone()[0] == 0


def test_changed_migration_is_rejected_before_initialization(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "migrations" / "sqlite"
    migrations = tmp_path / "migrations"
    shutil.copytree(source, migrations)
    initial = migrations / "001_initial.sql"
    initial.write_text(initial.read_text(encoding="utf-8") + "\n-- changed\n")

    with pytest.raises(StoreNotInitializedError, match="checksum mismatch"):
        SqliteMemoryStore(tmp_path / "memory.db", migrations).initialize()


def test_manifest_targets_current_logical_fingerprint() -> None:
    manifest = json.loads(
        (REPOSITORY_ROOT / "migrations" / "sqlite" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (REPOSITORY_ROOT / "schema" / "current.json").read_text(encoding="utf-8")
    )
    assert (
        manifest["migrations"][-1]["target_fingerprint"] == schema["schema_fingerprint"]
    )


def test_failed_migration_rolls_back_its_partial_schema(tmp_path: Path) -> None:
    database = tmp_path / "version-one.db"
    source = REPOSITORY_ROOT / "migrations" / "sqlite"
    migrations = tmp_path / "migrations"
    shutil.copytree(source, migrations)
    with sqlite3.connect(database) as connection:
        connection.executescript(
            (source / "001_initial.sql").read_text(encoding="utf-8")
        )
    second = migrations / "002_useful_querying.sql"
    second.write_text(
        second.read_text(encoding="utf-8")
        + "\nCREATE TABLE partial_marker (id INTEGER);\nSELECT missing_function();\n",
        encoding="utf-8",
    )
    manifest_path = migrations / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["migrations"][1]["checksum"] = sha256_bytes(second.read_bytes())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(StoreNotInitializedError, match="migration failed"):
        SqliteMemoryStore(database, migrations).initialize()

    with sqlite3.connect(database) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        partial = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'partial_marker'"
        ).fetchone()
    assert version == 1
    assert partial is None
