from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from analytical_memory.canonical import canonical_json, sha256_json
from analytical_memory.cli import main
from analytical_memory.errors import BatchValidationError

from .conftest import ApplicationFixture


def test_capabilities_are_discoverable_and_path_free(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    before = fixture.application.capabilities()
    fingerprint = str(before.pop("runtime_fingerprint"))

    assert fingerprint == sha256_json(before)
    assert before["storage"] == {
        "backend": "sqlite",
        "initialized": False,
        "migration_version": 0,
    }
    assert before["saved_queries"] == [
        "current-facts",
        "current-metric",
        "current-slots",
        "search-text",
        "traverse-relations",
    ]
    assert "NodeAttribute" in before["record_types"]
    assert before["limits"]["ingestion_batch_bytes"] == 1_048_576
    assert before["evidence_store"]["raw_read"] == {
        "enabled": False,
        "max_bytes": 0,
    }
    assert str(fixture.database) not in canonical_json(before)
    assert str(fixture.evidence_store.root) not in canonical_json(before)
    assert not fixture.database.exists()
    assert not fixture.evidence_store.root.exists()


def test_status_and_validation_follow_runtime_state(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    assert fixture.application.status()["ready"] is False
    unavailable = fixture.application.validate()
    assert unavailable["ok"] is False
    assert unavailable["issues"] == [
        "memory store is not initialized",
        "evidence store is not initialized",
    ]

    fixture.application.initialize()
    fixture.application.apply(fixture.batch_path)
    healthy = fixture.application.validate()
    assert fixture.application.status()["ready"] is True
    assert healthy["ok"] is True
    assert healthy["integrity"]["ok"] is True
    assert healthy["evidence"]["checks"][0]["verification"] == "verified"

    digest = str(healthy["evidence"]["checks"][0]["digest"])
    fixture.evidence_store.object_path(digest).unlink()
    missing = fixture.application.validate()
    assert missing["ok"] is False
    assert missing["evidence"]["checks"][0]["availability"] == "missing"


def test_cli_status_and_validate_exit_codes(
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
    assert main([*shared, "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["ready"] is False

    assert main([*shared, "validate"]) == 1
    invalid = json.loads(capsys.readouterr().out)
    assert invalid["ok"] is False

    assert main([*shared, "init"]) == 0
    capsys.readouterr()
    assert main([*shared, "validate"]) == 0
    valid = json.loads(capsys.readouterr().out)
    assert valid["ok"] is True


def test_batch_size_limit_is_enforced(
    application_fixture: ApplicationFixture,
    tmp_path: Path,
) -> None:
    fixture = application_fixture
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * 1_048_577)

    with pytest.raises(BatchValidationError, match="maximum size"):
        fixture.application.preview(oversized)


def test_explain_addresses_a_fact_beyond_the_query_return_limit(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    document = json.loads(fixture.batch_path.read_text(encoding="utf-8"))
    document["nodes"][0]["attributes"] = [
        {
            "assertions": [],
            "cardinality": "single",
            "name": f"item-{index:04d}",
            "privacy_class": "public",
            "value": index,
        }
        for index in range(1_001)
    ]
    fixture.batch_path.write_text(
        json.dumps(document, separators=(",", ":")), encoding="utf-8"
    )
    fixture.application.initialize()
    plan = fixture.application.plan(fixture.batch_path)
    fixture.application.apply(fixture.batch_path)

    current = fixture.application.current_facts()
    last_attribute_id = plan.attributes[-1].id
    explanation = fixture.application.explain(last_attribute_id)

    assert len(current["results"]) == 1_000
    assert all(item["attribute_id"] != last_attribute_id for item in current["results"])
    assert explanation["fact"]["attribute_id"] == last_attribute_id
    assert explanation["fact"]["state"] == "unasserted"
