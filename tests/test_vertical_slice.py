from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from analytical_memory.cli import main

from .conftest import REPOSITORY_ROOT, ApplicationFixture


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _table_counts(database: Path) -> dict[str, int]:
    tables = (
        "ingestion_batch",
        "source",
        "analytical_run",
        "node",
        "node_attribute",
        "assertion",
        "evidence_object",
        "evidence_fragment",
        "evidence_binding",
    )
    with sqlite3.connect(database) as connection:
        return {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in tables
        }


def test_preview_is_non_writing(application_fixture: ApplicationFixture) -> None:
    preview = application_fixture.application.preview(application_fixture.batch_path)

    assert preview["writes"] is False
    assert preview["counts"] == {
        "assertions": 4,
        "attributes": 4,
        "bindings": 4,
        "evidence_objects": 1,
        "nodes": 1,
        "runs": 1,
        "sources": 1,
    }
    assert not application_fixture.database.exists()
    assert not application_fixture.evidence_store.root.exists()


def test_apply_query_explain_and_exact_replay(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    first = fixture.application.apply(fixture.batch_path)
    counts_after_first = _table_counts(fixture.database)
    replay = fixture.application.apply(fixture.batch_path)

    assert first["replayed"] is False
    assert replay == {"replayed": True, "result": first["result"]}
    assert _table_counts(fixture.database) == counts_after_first
    assert counts_after_first == {
        "ingestion_batch": 1,
        "source": 1,
        "analytical_run": 1,
        "node": 1,
        "node_attribute": 4,
        "assertion": 4,
        "evidence_object": 1,
        "evidence_fragment": 1,
        "evidence_binding": 4,
    }

    golden = _read_json(REPOSITORY_ROOT / "tests" / "golden" / "current_facts.json")
    current = fixture.application.current_facts()
    assert current == golden

    supported = next(
        fact for fact in current["results"] if fact["state"] == "supported"
    )
    explanation = fixture.application.explain(str(supported["attribute_id"]))
    assert explanation["fact"] == supported
    assert len(explanation["assertions"]) == 1
    binding = explanation["assertions"][0]["evidence"][0]
    assert binding["locator"] == {"kind": "whole_object"}
    assert binding["status"] == {
        "availability": "present",
        "verification": "verified",
        "byte_size": 62,
    }
    assert fixture.memory_store.integrity() == {
        "foreign_key_errors": 0,
        "integrity": ["ok"],
        "ok": True,
        "schema_version": 1,
    }


def test_explain_reports_missing_evidence(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    applied = fixture.application.apply(fixture.batch_path)
    digest = str(applied["result"]["evidence_digest"])
    fixture.evidence_store.object_path(digest).unlink()

    attribute_id = str(applied["result"]["attribute_ids"][0])
    explanation = fixture.application.explain(attribute_id)
    status = explanation["assertions"][0]["evidence"][0]["status"]
    assert status["availability"] == "missing"
    assert status["verification"] == "unverified"


def test_new_assertion_supersedes_without_mutating_history(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    first_plan = fixture.application.plan(fixture.batch_path)
    fixture.application.apply(fixture.batch_path)

    document = _read_json(fixture.batch_path)
    document["idempotency_key"] = "quickstart-supersession-v1"
    document["recorded_at"] = "2000-01-02T00:00:00Z"
    node = document["nodes"][0]
    node["attributes"] = [node["attributes"][0]]
    replacement = node["attributes"][0]["assertions"][0]
    replacement["stance"] = "contradicts"
    replacement["supersedes_assertion_id"] = first_plan.assertions[0].id
    fixture.batch_path.write_text(json.dumps(document), encoding="utf-8")

    fixture.application.apply(fixture.batch_path)
    current = fixture.application.current_facts()
    fact = next(
        item
        for item in current["results"]
        if item["attribute_name"] == "supported_state"
    )
    explanation = fixture.application.explain(str(fact["attribute_id"]))

    assert fact["state"] == "contradicted"
    assert len(explanation["assertions"]) == 2
    assert [item["effective"] for item in explanation["assertions"]] == [False, True]


def test_cli_runs_the_public_vertical_slice(
    application_fixture: ApplicationFixture,
    capsys: Any,
) -> None:
    fixture = application_fixture
    shared = [
        "--database",
        str(fixture.database),
        "--evidence-root",
        str(fixture.evidence_store.root),
    ]
    assert main([*shared, "init"]) == 0
    capsys.readouterr()
    assert main([*shared, "ingest", "apply", str(fixture.batch_path)]) == 0
    capsys.readouterr()
    assert main([*shared, "query", "current-facts"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == _read_json(
        REPOSITORY_ROOT / "tests" / "golden" / "current_facts.json"
    )
