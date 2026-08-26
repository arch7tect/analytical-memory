from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from analytical_memory.api import MemoryAPI
from analytical_memory.configuration import build_application
from analytical_memory.schema_compiler import schema_is_current

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="analytical-memory-querying-") as directory:
        root = Path(directory)
        example = root / "querying"
        shutil.copytree(REPOSITORY_ROOT / "examples" / "querying", example)
        application = build_application(
            database=root / "memory.db",
            evidence_root=root / "evidence",
            schema_path=REPOSITORY_ROOT / "schema" / "current.json",
        )
        api = MemoryAPI(application)
        application.initialize()
        plan = application.plan(example / "batch.json")
        api.ingestion_apply(example / "batch.json")
        slots = api.query_current_slots().model_dump(mode="json")["results"]
        metric = api.query_current_metric(
            "example.count.v1", {"scope": "all"}
        ).model_dump(mode="json")
        traversal = api.traverse_relations(
            plan.nodes[0].id,
            relation_types=["example:links"],
            max_depth=2,
        ).model_dump(mode="json")
        search = api.search_text("connected", 10).model_dump(mode="json")
        relation_explanation = api.explain_relation(plan.relations[0].id).model_dump(
            mode="json"
        )
        metric_explanation = api.explain_metric(plan.metrics[0].id).model_dump(
            mode="json"
        )

        statuses = {str(item["attribute_name"]): str(item["status"]) for item in slots}
        result: dict[str, Any] = {
            "metric_value": metric["metric"]["value"],
            "migration_versions": [
                item["version"]
                for item in application.memory_store.integrity()["migrations"]
            ],
            "relation_evidence": relation_explanation["assertions"][0]["evidence"][0][
                "status"
            ]["verification"],
            "metric_evidence": metric_explanation["evidence"][0]["status"][
                "verification"
            ],
            "schema_compiled": schema_is_current(),
            "search_results": len(search["results"]),
            "slot_statuses": statuses,
            "traversal_nodes": len(traversal["nodes"]),
        }
        if result != {
            "metric_value": 3,
            "migration_versions": [1, 2],
            "relation_evidence": "verified",
            "metric_evidence": "verified",
            "schema_compiled": True,
            "search_results": 1,
            "slot_statuses": {
                "description": "current",
                "pending": "missing",
                "review": "contested",
                "status": "conflict",
                "tag": "values",
            },
            "traversal_nodes": 3,
        }:
            raise RuntimeError(f"unexpected querying smoke result: {result}")
        print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
