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


def test_version_one_database_is_upgraded_and_backfilled(tmp_path: Path) -> None:
    database = tmp_path / "version-one.db"
    initial = REPOSITORY_ROOT / "migrations" / "sqlite" / "001_initial.sql"
    with sqlite3.connect(database) as connection:
        connection.executescript(initial.read_text(encoding="utf-8"))
        connection.executescript(
            """
            INSERT INTO ingestion_batch VALUES (
                'batch', 'legacy-batch', 'input-hash', 'legacy-schema', '{}',
                '2000-01-01T00:00:00Z'
            );
            INSERT INTO source VALUES (
                'source', 'legacy-source', 'synthetic', 'example://legacy',
                'public', '2000-01-01T00:00:00Z'
            );
            INSERT INTO analytical_run VALUES (
                'run', 'legacy-run', 'batch', 'source',
                '2000-01-01T00:00:00Z', NULL, 'legacy-method',
                '2000-01-01T00:00:00Z'
            );
            INSERT INTO node VALUES (
                'node', 'example', 'record', 'legacy-node', NULL, 'public',
                '2000-01-01T00:00:00Z'
            );
            INSERT INTO node_attribute VALUES (
                'attribute', 'node', 'status', 'single', '"value"', 'value-hash',
                'public', '2000-01-01T00:00:00Z'
            );
            INSERT INTO assertion VALUES (
                'assertion', 'attribute', 'supports', 'observed', 1.0,
                'reviewed', '2000-01-01T00:00:00Z', NULL,
                '2000-01-01T00:00:00Z', 'legacy-method', 'source', 'run', NULL,
                'active', 'assertion-stable-key'
            );
            INSERT INTO evidence_object VALUES (
                'object',
                '0000000000000000000000000000000000000000000000000000000000000000',
                0, 'text/plain', 'public', '2000-01-01T00:00:00Z'
            );
            INSERT INTO evidence_fragment VALUES (
                'fragment', 'object', 'whole_object', '{"kind":"whole_object"}',
                'identity', '1', 0,
                '0000000000000000000000000000000000000000000000000000000000000000',
                'public', '2000-01-01T00:00:00Z'
            );
            INSERT INTO evidence_binding VALUES (
                'binding', 'assertion', 'fragment', 'supports', 1.0, 'reviewed',
                '2000-01-01T00:00:00Z'
            );
            """
        )
    store = SqliteMemoryStore(database)

    store.initialize()
    integrity = store.integrity()

    assert integrity["schema_version"] == 2
    assert [item["version"] for item in integrity["migrations"]] == [1, 2]
    assert integrity["migrations"][0]["checksum"] == (
        "328ec2c72de2af17c4aeb0fa072302148497220d8051edb50c666a1d6ef1ef94"
    )
    assert store.current_facts()[0]["state"] == "supported"
    with sqlite3.connect(database) as connection:
        searchable, stable_key_version = connection.execute(
            """
            SELECT node_attribute.searchable, assertion.stable_key_version
            FROM node_attribute
            JOIN assertion ON assertion.attribute_id = node_attribute.id
            WHERE node_attribute.id = 'attribute'
            """
        ).fetchone()
    assert searchable == 0
    assert stable_key_version == 1
    assert (
        store.explain_attribute("attribute")["assertions"][0]["evidence"][0][
            "binding_id"
        ]
        == "binding"
    )


def test_changed_migration_is_rejected_before_initialization(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "migrations" / "sqlite"
    migrations = tmp_path / "migrations"
    shutil.copytree(source, migrations)
    initial = migrations / "001_initial.sql"
    initial.write_text(initial.read_text(encoding="utf-8") + "\n-- changed\n")
    store = SqliteMemoryStore(tmp_path / "memory.db", migrations)

    with pytest.raises(StoreNotInitializedError, match="checksum mismatch"):
        store.initialize()


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
