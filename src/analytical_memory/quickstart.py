from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(
        description="Run an isolated, reproducible walkthrough."
    )
    parser.add_argument("--smoke", action="store_true", help="Original tiny v1 fixture")
    parser.add_argument(
        "--json", action="store_true", help="Versioned machine-readable results"
    )
    parser.add_argument(
        "--memory",
        help="Run in an already configured empty named memory; retain all data",
    )
    parser.add_argument(
        "--extensions",
        action="store_true",
        help="Also verify incremental joins, rollback, search, privacy and restore",
    )
    arguments = parser.parse_args()
    if arguments.smoke:
        print(json.dumps(run_quickstart(), indent=2, sort_keys=True))
        return
    from analytical_memory.retail_quickstart import human_report, run_isolated_retail

    if arguments.memory:
        from analytical_memory.api import MemoryAPI
        from analytical_memory.configuration import (
            build_application,
            environment_memory_catalog,
        )
        from analytical_memory.memories import MemoryRouter
        from analytical_memory.retail_quickstart import run_retail

        if arguments.memory == "default":
            parser.error("choose a dedicated named memory")
        _, application = MemoryRouter(
            build_application(), environment_memory_catalog()
        ).resolve(arguments.memory)
        api = MemoryAPI(application)
        result = run_retail(api)
        if arguments.extensions:
            from analytical_memory.retail_quickstart import run_extensions

            result["extensions"] = run_extensions(api)
    else:
        result = run_isolated_retail(extensions=arguments.extensions)
    print(
        json.dumps(result, indent=2, sort_keys=True)
        if arguments.json
        else human_report(result)
    )
