from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from analytical_memory.canonical import canonical_json, sha256_bytes, strict_json_loads
from analytical_memory.errors import TransferError
from analytical_memory.limits import MAX_SNAPSHOT_BYTES
from analytical_memory.ports import EvidenceStore, MemoryStore
from analytical_memory.schema_contract import SchemaContract

TRANSFER_KIND = "canonical-backend-transfer"
TRANSFER_VERSION = "2"


def create_transfer(
    store: MemoryStore,
    schema: SchemaContract,
    destination: Path,
    created_at: str,
    evidence_store: EvidenceStore | None = None,
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
    manifests = {}
    for observation in records.get("analysis_observation", []):
        digest = observation["manifest_digest"]
        if evidence_store is None:
            raise TransferError("native observations require an evidence store")
        from analytical_memory.native_store import read_manifest

        payload = canonical_json(read_manifest(evidence_store, digest)).encode()
        if sha256_bytes(payload) != digest:
            raise TransferError("native manifest is not canonical")
        manifests[digest] = base64.b64encode(payload).decode("ascii")
    body["analysis_manifests"] = manifests
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
        document = strict_json_loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TransferError(f"cannot read transfer: {source}") from exc
    if not isinstance(document, dict):
        raise TransferError("transfer document must be an object")
    from analytical_memory.resources import resource_path

    legacy_schema = strict_json_loads(
        resource_path("schema", "legacy-0.6.1.json").read_text()
    )
    legacy = (
        document.get("format_version") == "1"
        and document.get("schema_fingerprint") == legacy_schema["schema_fingerprint"]
    )
    if (
        document.get("artifact_kind") != TRANSFER_KIND
        or (not legacy and document.get("format_version") != TRANSFER_VERSION)
        or (not legacy and document.get("schema_fingerprint") != expected_fingerprint)
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
    if legacy:
        from analytical_memory.adapters.sql_store import SNAPSHOT_TABLES

        if set(records) != set(SNAPSHOT_TABLES) - {"analysis_observation"}:
            raise TransferError("legacy transfer table set does not match")
        records["analysis_observation"] = []
        for row in records["metric"]:
            row["origin"] = "caller"
        document["original_table_hashes"] = document["table_hashes"]
        document["table_hashes"] = {
            table: sha256_bytes(canonical_json(rows).encode())
            for table, rows in sorted(records.items())
        }
        document["adapted_from"] = "0.6.1"
    required = {
        row["manifest_digest"] for row in records.get("analysis_observation", [])
    }
    manifests = document.get("analysis_manifests", {})
    if not isinstance(manifests, dict) or set(manifests) != required:
        raise TransferError("native manifest set does not match observations")
    for digest, encoded in manifests.items():
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise TransferError("invalid native manifest encoding") from exc
        if sha256_bytes(data) != digest:
            raise TransferError("native manifest failed verification")
    return document
