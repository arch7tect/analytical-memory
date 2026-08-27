from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from analytical_memory.canonical import canonical_json, sha256_bytes
from analytical_memory.errors import TransferError
from analytical_memory.limits import MAX_SNAPSHOT_BYTES
from analytical_memory.ports import MemoryStore
from analytical_memory.schema_contract import SchemaContract

TRANSFER_KIND = "canonical-backend-transfer"
TRANSFER_VERSION = "1"


def create_transfer(
    store: MemoryStore,
    schema: SchemaContract,
    destination: Path,
    created_at: str,
) -> dict[str, Any]:
    if destination.exists():
        raise TransferError(f"transfer destination already exists: {destination}")
    records = store.transfer_records()
    table_hashes = {
        table: sha256_bytes(canonical_json(rows).encode("utf-8"))
        for table, rows in sorted(records.items())
    }
    body: dict[str, Any] = {
        "artifact_kind": TRANSFER_KIND,
        "created_at": created_at,
        "format_version": TRANSFER_VERSION,
        "ontology_fingerprint": store.ontology_snapshot()["ontology_fingerprint"],
        "records": records,
        "row_counts": {table: len(rows) for table, rows in sorted(records.items())},
        "schema_fingerprint": schema.fingerprint,
        "source_backend": store.status().backend,
        "table_hashes": table_hashes,
    }
    body["transfer_id"] = sha256_bytes(canonical_json(body).encode("utf-8"))
    data = (
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise TransferError("transfer exceeds the size limit")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise TransferError(
                f"transfer destination already exists: {destination}"
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return body


def load_transfer(source: Path, expected_fingerprint: str) -> dict[str, Any]:
    try:
        if source.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise TransferError("transfer exceeds the size limit")
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransferError(f"cannot read transfer: {source}") from exc
    if not isinstance(document, dict):
        raise TransferError("transfer document must be an object")
    if (
        document.get("artifact_kind") != TRANSFER_KIND
        or document.get("format_version") != TRANSFER_VERSION
        or document.get("schema_fingerprint") != expected_fingerprint
    ):
        raise TransferError("transfer contract does not match")
    identity = dict(document)
    transfer_id = identity.pop("transfer_id", None)
    if transfer_id != sha256_bytes(canonical_json(identity).encode("utf-8")):
        raise TransferError("transfer identity does not match")
    records = document.get("records")
    if not isinstance(records, dict) or not all(
        isinstance(table, str)
        and isinstance(rows, list)
        and all(isinstance(row, dict) for row in rows)
        for table, rows in records.items()
    ):
        raise TransferError("transfer records have an invalid shape")
    row_counts = {table: len(rows) for table, rows in sorted(records.items())}
    table_hashes = {
        table: sha256_bytes(canonical_json(rows).encode("utf-8"))
        for table, rows in sorted(records.items())
    }
    if (
        document.get("row_counts") != row_counts
        or document.get("table_hashes") != table_hashes
    ):
        raise TransferError("transfer record verification failed")
    return document
