from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from analytical_memory.resources import resource_path

EXAMPLES = resource_path("examples", "quickstart")


def _run(working_directory: Path, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "analytical_memory.cli", *arguments],
        cwd=working_directory,
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("command did not return a JSON object")
    return value


def run_quickstart() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="analytical-memory-quickstart-") as raw:
        root = Path(raw)
        shared = (
            "--database",
            str(root / "memory.db"),
            "--evidence-root",
            str(root / "evidence"),
        )
        _run(root, *shared, "init")
        fingerprint = str(_run(root, *shared, "schema", "show")["schema_fingerprint"])
        for filename, entity_type in (
            ("sessions.jsonl", "example.Session"),
            ("messages.jsonl", "example.SessionMessage"),
        ):
            _run(
                root,
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
        joined = _run(
            root,
            *shared,
            "join",
            "materialize",
            str(EXAMPLES / "join.json"),
            "--contract-fingerprint",
            fingerprint,
        )
        queried = _run(
            root,
            *shared,
            "query",
            "execute",
            "--document",
            str(EXAMPLES / "query.json"),
        )
    if joined["created_relations"] != 2 or len(queried["rows"]) != 1:
        raise RuntimeError("quickstart result is unexpected")
    return {
        "created_relations": joined["created_relations"],
        "ok": True,
        "query_rows": len(queried["rows"]),
    }


def main() -> None:
    print(json.dumps(run_quickstart(), indent=2, sort_keys=True))
