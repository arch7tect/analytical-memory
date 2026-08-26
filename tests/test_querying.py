from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from .conftest import ApplicationFixture


def test_slots_relations_metrics_traversal_search_and_explanation(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    plan = fixture.application.plan(querying_batch_path)
    applied = fixture.application.apply(querying_batch_path)

    assert len(applied["result"]["relation_ids"]) == 3
    assert len(applied["result"]["metric_ids"]) == 1
    assert len(applied["result"]["search_document_ids"]) == 2

    slots = fixture.application.current_slots()["results"]
    slots_by_name = {
        (slot["natural_key"], slot["attribute_name"]): slot for slot in slots
    }
    assert slots_by_name[("record-a", "status")]["status"] == "conflict"
    assert slots_by_name[("record-a", "status")]["current_value"] is None
    assert slots_by_name[("record-a", "pending")]["status"] == "missing"
    assert slots_by_name[("record-a", "review")]["status"] == "contested"
    assert slots_by_name[("record-a", "tag")]["status"] == "values"
    assert [
        candidate["state"]
        for candidate in slots_by_name[("record-a", "tag")]["candidates"]
    ] == ["contested", "supported"]

    metric = fixture.application.current_metric("example.count.v1", {"scope": "all"})
    assert metric["coverage"] == {"complete": True, "selected_count": 1}
    assert metric["metric"]["value"] == 3
    metric_explanation = fixture.application.explain_metric(plan.metrics[0].id)
    assert metric_explanation["evidence"][0]["role"] == "contextualizes"
    assert metric_explanation["evidence"][0]["status"]["verification"] == "verified"

    traversal = fixture.application.traverse_relations(
        plan.nodes[0].id,
        relation_types=["example:links"],
        max_depth=2,
    )
    assert [node["natural_key"] for node in traversal["nodes"]] == [
        "record-a",
        "record-b",
        "record-c",
    ]
    assert [edge["state"] for edge in traversal["edges"]] == [
        "supported",
        "supported",
    ]
    contradicted = fixture.application.traverse_relations(
        plan.nodes[0].id,
        states=["contradicted"],
        max_depth=1,
    )
    assert [node["natural_key"] for node in contradicted["nodes"]] == [
        "record-a",
        "record-c",
    ]

    relation_explanation = fixture.application.explain_relation(plan.relations[0].id)
    assert relation_explanation["fact"]["state"] == "supported"
    assert (
        relation_explanation["assertions"][0]["evidence"][0]["status"]["verification"]
        == "verified"
    )

    search = fixture.application.search_text("connected", limit=10)
    assert search["coverage"] == {
        "eligible_count": 2,
        "indexed_count": 2,
        "complete": True,
    }
    assert len(search["results"]) == 1
    assert search["results"][0]["fact"]["natural_key"] == "record-a"
    assert (
        search["results"][0]["provenance"]["assertions"][0]["evidence"][0]["status"][
            "verification"
        ]
        == "verified"
    )


def test_current_metric_selects_latest_complete_run_deterministically(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    fixture.application.apply(querying_batch_path)
    document = json.loads(querying_batch_path.read_text(encoding="utf-8"))
    document["idempotency_key"] = "querying-batch-v2"
    document["recorded_at"] = "2000-02-02T00:00:00Z"
    document["run"]["valid_from"] = "2000-02-02T00:00:00Z"
    document["nodes"] = [{**document["nodes"][0], "attributes": []}]
    document["relations"] = []
    document["metrics"][0]["value"] = 4
    document["metrics"][0]["numerator"] = 4
    document["metrics"][0]["coverage"] = {"observed": 4, "total": 4}
    querying_batch_path.write_text(json.dumps(document), encoding="utf-8")

    second_plan = fixture.application.plan(querying_batch_path)
    fixture.application.apply(querying_batch_path)
    selected = fixture.application.current_metric("example.count.v1", {"scope": "all"})

    assert selected["metric"]["metric_id"] == second_plan.metrics[0].id
    assert selected["metric"]["value"] == 4


def test_traversal_enforces_limits_and_does_not_follow_attributes(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    plan = fixture.application.plan(querying_batch_path)
    fixture.application.apply(querying_batch_path)

    limited = fixture.application.traverse_relations(
        plan.nodes[0].id, max_depth=2, limit=2
    )
    assert len(limited["nodes"]) == 2
    assert limited["truncated"] is True

    start_only = fixture.application.traverse_relations(
        plan.nodes[0].id, max_depth=2, limit=1
    )
    assert len(start_only["nodes"]) == 1
    assert start_only["edges"] == []
    assert start_only["truncated"] is True

    with sqlite3.connect(fixture.database) as connection:
        for index in (1, 2):
            relation_id = f"parallel-relation-{index}"
            connection.execute(
                """
                INSERT INTO relation VALUES (?, ?, 'example:links', ?, ?, 'public', ?)
                """,
                (
                    relation_id,
                    plan.nodes[0].id,
                    plan.nodes[1].id,
                    f"parallel-{index}",
                    plan.recorded_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO assertion VALUES (
                    ?, 'relation', ?, NULL, ?, 'supports', 'observed', 1.0,
                    'unreviewed', ?, NULL, ?, 'synthetic-relation-v1', ?, ?,
                    NULL, 'active', ?, 2
                )
                """,
                (
                    f"parallel-assertion-{index}",
                    relation_id,
                    relation_id,
                    plan.run.valid_from,
                    plan.recorded_at,
                    plan.source.id,
                    plan.run.id,
                    f"parallel-stable-key-{index}",
                ),
            )
    parallel_limited = fixture.application.traverse_relations(
        plan.nodes[0].id, max_depth=1, limit=2
    )
    assert len(parallel_limited["edges"]) == 2
    assert parallel_limited["truncated"] is True

    no_types = fixture.application.traverse_relations(
        plan.nodes[0].id, relation_types=[], max_depth=2
    )
    assert no_types["edges"] == []

    with sqlite3.connect(fixture.database) as connection:
        connection.execute(
            "DELETE FROM search_document_fts WHERE document_id = ?",
            (plan.search_documents[0].id,),
        )
    coverage = fixture.application.search_text("calibration")["coverage"]
    assert coverage == {"eligible_count": 2, "indexed_count": 1, "complete": False}

    with pytest.raises(ValueError, match="word or number"):
        fixture.application.search_text("!!!")


def test_explanation_reports_retracted_assertion_as_ineffective(
    application_fixture: ApplicationFixture,
) -> None:
    fixture = application_fixture
    fixture.application.initialize()
    plan = fixture.application.plan(fixture.batch_path)
    fixture.application.apply(fixture.batch_path)
    assertion = plan.assertions[0]
    with sqlite3.connect(fixture.database) as connection:
        connection.execute(
            "UPDATE assertion SET lifecycle = 'retracted' WHERE id = ?",
            (assertion.id,),
        )

    explanation = fixture.application.explain(str(assertion.attribute_id))
    explained = next(
        item
        for item in explanation["assertions"]
        if item["assertion_id"] == assertion.id
    )
    assert explained["lifecycle"] == "retracted"
    assert explained["effective"] is False
    assert explained["stable_key"] == assertion.stable_key
    assert explained["stable_key_version"] == 2
    assert explanation["fact"]["state"] == "unasserted"
