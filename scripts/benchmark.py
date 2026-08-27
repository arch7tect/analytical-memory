from __future__ import annotations

import argparse
import json
import platform
import resource
import sqlite3
import sys
import tempfile
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.application import MemoryApplication
from analytical_memory.schema_contract import load_schema

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPOSITORY_ROOT / "benchmarks" / "baseline.json"


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> bytes:
    data = b"".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n"
        for row in rows
    )
    path.write_bytes(data)
    return data


def measure(records_per_type: int) -> dict[str, Any]:
    if records_per_type < 1:
        raise ValueError("records_per_type must be positive")
    with tempfile.TemporaryDirectory(prefix="analytical-memory-benchmark-") as raw:
        root = Path(raw)
        sessions = _jsonl(
            root / "sessions.jsonl",
            [
                {
                    "id": f"s{index:06d}",
                    "score": index,
                    "status": "completed" if index % 2 == 0 else "failed",
                }
                for index in range(records_per_type)
            ],
        )
        messages = _jsonl(
            root / "messages.jsonl",
            [
                {
                    "id": f"m{index:06d}",
                    "message": f"Synthetic message {index}",
                    "sequence": index,
                    "session_id": f"s{index:06d}",
                }
                for index in range(records_per_type)
            ],
        )
        database = root / "memory.db"
        evidence_root = root / "evidence"
        application = MemoryApplication(
            SqliteMemoryStore(database), FileEvidenceStore(evidence_root), load_schema()
        )
        started = time.monotonic()
        application.initialize()
        imports = []
        for path, entity_type in (
            (root / "sessions.jsonl", "benchmark.Session"),
            (root / "messages.jsonl", "benchmark.Message"),
        ):
            imports.append(
                application.jsonl_import(
                    path,
                    entity_type=entity_type,
                    key=[{"field": "id", "type": "string"}],
                    contract_fingerprint=application.schema.fingerprint,
                )
            )
        joined = application.materialize_join(
            name="message_to_session",
            relation="session",
            from_={"type": "benchmark.Message", "fields": ["session_id"]},
            to={"type": "benchmark.Session", "fields": ["id"]},
            contract_fingerprint=application.schema.fingerprint,
        )
        duration = time.monotonic() - started
        rows = application.memory_store.snapshot_records()
        evidence_bytes = sum(
            path.stat().st_size
            for path in (evidence_root / "objects" / "sha256").glob("*/*")
        )
        raw_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        rss_multiplier = 1 if sys.platform == "darwin" else 1024
        deterministic = {
            "attributes_written": sum(
                int(item["attributes_written"]) for item in imports
            ),
            "corpus_sha256": sha256(sessions + messages).hexdigest(),
            "created_nodes": sum(int(item["created_nodes"]) for item in imports),
            "created_relations": int(joined["created_relations"]),
            "evidence_bytes": evidence_bytes,
            "ontology_fingerprint": application.ontology()["ontology_fingerprint"],
            "record_count": records_per_type * 2,
            "row_counts": {
                table: len(table_rows) for table, table_rows in sorted(rows.items())
            },
            "schema_fingerprint": application.schema.fingerprint,
        }
        observed = {
            "backend": "sqlite",
            "database_bytes": database.stat().st_size,
            "duration_seconds": round(duration, 6),
            "machine": platform.machine(),
            "peak_rss_bytes": raw_rss * rss_multiplier,
            "platform": platform.system(),
            "python_version": platform.python_version(),
            "sqlite_version": sqlite3.sqlite_version,
        }
        return {
            "baseline_version": "1",
            "deterministic": deterministic,
            "observed": observed,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--records-per-type", type=int, default=500)
    arguments = parser.parse_args()
    result = measure(arguments.records_per_type)
    if arguments.check:
        expected = json.loads(arguments.output.read_text(encoding="utf-8"))
        if expected.get("deterministic") != result["deterministic"]:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
