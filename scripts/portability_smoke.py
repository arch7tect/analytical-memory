from __future__ import annotations

import tempfile
from pathlib import Path

from analytical_memory.configuration import build_application

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPOSITORY_ROOT / "schema" / "current.json"
BATCH = REPOSITORY_ROOT / "examples" / "quickstart" / "batch.json"


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="analytical-memory-portability-") as root:
        workspace = Path(root)
        source = build_application(
            database=workspace / "source" / "memory.db",
            evidence_root=workspace / "source" / "evidence",
            schema_path=SCHEMA,
        )
        source.initialize()
        applied = source.apply(BATCH)
        before = source.current_facts()
        snapshot = workspace / "portable.snapshot.zip"
        created = source.snapshot_create(snapshot, created_at="2001-01-01T00:00:00Z")
        verified = source.snapshot_verify(snapshot)

        target = build_application(
            database=workspace / "target" / "memory.db",
            evidence_root=workspace / "target" / "evidence",
            schema_path=SCHEMA,
        )
        imported = target.snapshot_import(snapshot)
        digest = str(applied["result"]["evidence_digest"])
        if target.current_facts() != before:
            raise RuntimeError("snapshot restore changed canonical query results")
        if target.evidence_status(digest)["verification"] != "verified":
            raise RuntimeError("snapshot restore did not install verified evidence")
        if verified["snapshot_id"] != imported["snapshot_id"]:
            raise RuntimeError("snapshot identity changed during restore")
        return {
            "evidence_verification": "verified",
            "fact_count": len(before["results"]),
            "ok": True,
            "snapshot_id": created["snapshot_id"],
        }


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2, sort_keys=True))
