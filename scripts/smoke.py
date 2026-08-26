from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPOSITORY_ROOT / "examples" / "quickstart"


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
        run(*shared, "init")
        fingerprint = str(run(*shared, "schema", "show")["schema_fingerprint"])
        for filename, entity_type in (
            ("sessions.jsonl", "example.Session"),
            ("messages.jsonl", "example.SessionMessage"),
        ):
            run(
                *shared,
                "jsonl",
                "import",
                str(EXAMPLES / filename),
                "--entity-type",
                entity_type,
                "--key",
                '[{"field":"id","type":"string"}]',
                "--contract-fingerprint",
                fingerprint,
            )
        joined = run(
            *shared,
            "join",
            "materialize",
            str(EXAMPLES / "join.json"),
            "--contract-fingerprint",
            fingerprint,
        )
        queried = run(
            *shared,
            "query",
            "execute",
            "--document",
            str(EXAMPLES / "query.json"),
        )
        if joined["created_relations"] != 2 or len(queried["rows"]) != 1:
            raise RuntimeError("M5 smoke result is unexpected")
        print(
            json.dumps(
                {
                    "created_relations": joined["created_relations"],
                    "ok": True,
                    "query_rows": len(queried["rows"]),
                },
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
