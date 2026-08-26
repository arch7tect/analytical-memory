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
        "evidence_acquisition",
        "evidence_derivation",
        "evidence_fragment",
        "evidence_binding",
        "evidence_location",
        "evidence_verification",
        "evidence_retirement",
        "relation",
        "metric",
        "search_document",
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
        "derivations": 0,
        "evidence_acquisitions": 1,
        "evidence_locations": 1,
        "evidence_objects": 1,
        "evidence_verifications": 1,
        "metrics": 0,
        "nodes": 1,
        "relations": 0,
        "runs": 1,
        "search_documents": 0,
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
        "evidence_acquisition": 1,
        "evidence_derivation": 0,
        "evidence_fragment": 1,
        "evidence_binding": 4,
        "evidence_location": 1,
        "evidence_verification": 1,
        "evidence_retirement": 0,
        "relation": 0,
        "metric": 0,
        "search_document": 0,
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
        "schema_version": 4,
        "migrations": [
            {
                "version": 1,
                "checksum": (
                    "328ec2c72de2af17c4aeb0fa072302148497220d8051edb50c666a1d6ef1ef94"
                ),
                "target_fingerprint": (
                    "21c6a71444f7d5725703ca31cc6e410c21958009b9bed902ad213a82a65c272f"
                ),
            },
            {
                "version": 2,
                "checksum": (
                    "c9459aba81bc8d2cb9a2411bc698dc8907f9e3f23c71979e8571a0bfe9ec172c"
                ),
                "target_fingerprint": (
                    "5161ccab9612c1c6b4cf99a980e1c29305ccdde2acc721851d1e160d53d0c953"
                ),
            },
            {
                "version": 3,
                "checksum": (
                    "41dcfcbce1eba85716d211e621df1ff5e2ded6655cbf2467251d51f221d2a93e"
                ),
                "target_fingerprint": (
                    "bf108e283cbf1b02ebda39cc3104c1f01a84d5d20479d7d310264453139a7e25"
                ),
            },
            {
                "version": 4,
                "checksum": (
                    "af068176d13e92c5c3662a55e3e4c0bf69f5ea716c325431729b5407fe2f37ef"
                ),
                "target_fingerprint": (
                    "5740c0e445a6b4bf215e6545618ef61dd34382052a1b886e2f7501a451446de0"
                ),
            },
        ],
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
