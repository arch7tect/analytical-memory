from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BATCH = REPOSITORY_ROOT / "examples" / "quickstart" / "batch.json"


def run(*arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "analytical_memory.cli", *arguments],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("command did not return a JSON object")
    return value


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="analytical-memory-smoke-") as directory:
        root = Path(directory)
        shared = (
            "--database",
            str(root / "memory.db"),
            "--evidence-root",
            str(root / "evidence"),
        )
        initialized = run(*shared, "init")
        preview = run(*shared, "ingest", "preview", str(BATCH))
        applied = run(*shared, "ingest", "apply", str(BATCH))
        replayed = run(*shared, "ingest", "apply", str(BATCH))
        current = run(*shared, "query", "current-facts")
        attribute_id = str(applied["result"]["attribute_ids"][0])
        explanation = run(*shared, "explain", attribute_id)

        states = {str(item["state"]) for item in current["results"]}
        evidence_status = explanation["assertions"][0]["evidence"][0]["status"]
        if not initialized["initialized"]:
            raise RuntimeError("initialization failed")
        if preview["writes"] is not False:
            raise RuntimeError("preview unexpectedly wrote state")
        if replayed != {"replayed": True, "result": applied["result"]}:
            raise RuntimeError("idempotent replay changed the result")
        if states != {"supported", "contested", "contradicted", "unasserted"}:
            raise RuntimeError("current-facts did not return all fact states")
        if evidence_status["verification"] != "verified":
            raise RuntimeError("evidence verification failed")

        print(
            json.dumps(
                {
                    "batch_id": applied["result"]["batch_id"],
                    "evidence_verification": evidence_status["verification"],
                    "fact_states": sorted(states),
                    "ok": True,
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
