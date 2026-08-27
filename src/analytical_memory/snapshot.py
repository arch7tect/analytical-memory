from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from analytical_memory.canonical import canonical_json, sha256_bytes, strict_json_loads
from analytical_memory.domain import EvidenceObjectRecord
from analytical_memory.errors import SnapshotError
from analytical_memory.limits import MAX_SNAPSHOT_BYTES, MAX_SNAPSHOT_MEMBERS
from analytical_memory.ports import EvidenceStore, MemoryStore
from analytical_memory.schema_contract import SchemaContract

SNAPSHOT_KIND = "private-restore-snapshot"
SNAPSHOT_VERSION = "1"


@dataclass(frozen=True, slots=True)
class SnapshotPayload:
    manifest: dict[str, Any]
    records: dict[str, list[dict[str, Any]]]
    object_bytes: dict[str, bytes]


def _member_name(digest: str) -> str:
    return f"objects/sha256/{digest[:2]}/{digest}"


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and name == path.as_posix()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    return info


def create_snapshot(
    memory_store: MemoryStore,
    evidence_store: EvidenceStore,
    schema: SchemaContract,
    destination: Path,
    created_at: str,
) -> dict[str, Any]:
    if destination.exists():
        raise SnapshotError(f"snapshot destination already exists: {destination}")
    records = memory_store.snapshot_records()
    if len(records["evidence_object"]) + 3 > MAX_SNAPSHOT_MEMBERS:
        raise SnapshotError("snapshot has too many members")
    records_bytes = canonical_json(records).encode("utf-8")
    schema_bytes = canonical_json(schema.document).encode("utf-8")
    locations = {
        str(row["evidence_object_id"]): row
        for row in records["evidence_location"]
        if row["provider"] == "local-filesystem" and row["root_id"] == "default"
    }
    retired = {str(row["evidence_object_id"]) for row in records["evidence_retirement"]}
    members: dict[str, bytes] = {
        "records.json": records_bytes,
        "schema.json": schema_bytes,
    }
    objects: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        for row in sorted(
            records["evidence_object"], key=lambda item: str(item["digest"])
        ):
            object_id = str(row["id"])
            digest = str(row["digest"])
            state = (
                "retired"
                if object_id in retired
                else str(locations.get(object_id, {}).get("availability", "missing"))
            )
            provider_status = evidence_store.stat(digest)
            if state != "retired" and provider_status.availability != state:
                raise SnapshotError(
                    f"persisted evidence location is stale; audit required: {digest}"
                )
            item: dict[str, Any] = {
                "byte_size": int(row["byte_size"]),
                "digest": digest,
                "state": state,
            }
            if state == "present":
                member = _member_name(digest)
                projected_size = sum(len(data) for data in members.values()) + int(
                    row["byte_size"]
                )
                if projected_size > MAX_SNAPSHOT_BYTES:
                    raise SnapshotError("snapshot exceeds the uncompressed size limit")
                staged = temporary_root / member
                try:
                    copied = evidence_store.copy_verified(digest, staged)
                except (OSError, ValueError) as exc:
                    raise SnapshotError(
                        f"evidence object is not verified: {digest}"
                    ) from exc
                if copied != int(row["byte_size"]):
                    raise SnapshotError(f"evidence size changed: {digest}")
                data = staged.read_bytes()
                if sha256_bytes(data) != digest:
                    raise SnapshotError(f"evidence digest changed: {digest}")
                members[member] = data
                item["member"] = member
            elif state not in {"missing", "retired"}:
                raise SnapshotError(f"unknown evidence snapshot state: {state}")
            objects.append(item)

    manifest_body: dict[str, Any] = {
        "artifact_kind": SNAPSHOT_KIND,
        "created_at": created_at,
        "format_version": SNAPSHOT_VERSION,
        "members": {
            name: {"byte_size": len(data), "sha256": sha256_bytes(data)}
            for name, data in sorted(members.items())
        },
        "objects": objects,
        "row_counts": {table: len(rows) for table, rows in sorted(records.items())},
        "schema_fingerprint": schema.fingerprint,
    }
    manifest_body["snapshot_id"] = sha256_bytes(
        canonical_json(manifest_body).encode("utf-8")
    )
    manifest_bytes = canonical_json(manifest_body).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary_path, "w") as archive:
            archive.writestr(_zip_info("manifest.json"), manifest_bytes)
            for name, data in sorted(members.items()):
                archive.writestr(_zip_info(name), data)
        os.chmod(temporary_path, 0o600)
        try:
            os.link(temporary_path, destination)
        except FileExistsError as exc:
            raise SnapshotError(
                f"snapshot destination already exists: {destination}"
            ) from exc
    finally:
        temporary_path.unlink(missing_ok=True)
    return manifest_body


def load_snapshot(source: Path, expected_fingerprint: str) -> SnapshotPayload:
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_SNAPSHOT_MEMBERS:
                raise SnapshotError("snapshot has too many members")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or not all(
                _safe_member(name) for name in names
            ):
                raise SnapshotError(
                    "snapshot contains unsafe or duplicate member names"
                )
            if sum(info.file_size for info in infos) > MAX_SNAPSHOT_BYTES:
                raise SnapshotError("snapshot exceeds the uncompressed size limit")
            manifest = strict_json_loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict):
                raise SnapshotError("snapshot manifest must be an object")
            if manifest.get("artifact_kind") != SNAPSHOT_KIND:
                raise SnapshotError("artifact is not a private restore snapshot")
            if manifest.get("format_version") != SNAPSHOT_VERSION:
                raise SnapshotError("snapshot format version is unsupported")
            if manifest.get("schema_fingerprint") != expected_fingerprint:
                raise SnapshotError("snapshot schema fingerprint does not match")
            identity_body = dict(manifest)
            snapshot_id = identity_body.pop("snapshot_id", None)
            if snapshot_id != sha256_bytes(
                canonical_json(identity_body).encode("utf-8")
            ):
                raise SnapshotError("snapshot identity does not match its manifest")
            declared_members = manifest.get("members")
            if not isinstance(declared_members, dict):
                raise SnapshotError("snapshot member manifest is invalid")
            if set(names) != {"manifest.json", *declared_members}:
                raise SnapshotError("snapshot members do not match the manifest")
            member_bytes: dict[str, bytes] = {}
            for name, expected in declared_members.items():
                if not isinstance(expected, dict):
                    raise SnapshotError("snapshot member metadata is invalid")
                data = archive.read(name)
                if len(data) != expected.get("byte_size") or sha256_bytes(
                    data
                ) != expected.get("sha256"):
                    raise SnapshotError(f"snapshot member failed verification: {name}")
                member_bytes[name] = data
    except (OSError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        if isinstance(exc, SnapshotError):
            raise
        raise SnapshotError(f"cannot read snapshot: {source}") from exc

    try:
        records = strict_json_loads(member_bytes["records.json"])
        schema_document = strict_json_loads(member_bytes["schema.json"])
    except (KeyError, ValueError) as exc:
        raise SnapshotError("snapshot canonical records are invalid") from exc
    if not isinstance(records, dict) or not all(
        isinstance(table, str) and isinstance(rows, list)
        for table, rows in records.items()
    ):
        raise SnapshotError("snapshot canonical records have an invalid shape")
    if not all(isinstance(row, dict) for rows in records.values() for row in rows):
        raise SnapshotError("snapshot canonical rows must be objects")
    if (
        not isinstance(schema_document, dict)
        or schema_document.get("schema_fingerprint") != expected_fingerprint
    ):
        raise SnapshotError("snapshot schema document does not match")
    row_counts = manifest.get("row_counts")
    if row_counts != {table: len(rows) for table, rows in sorted(records.items())}:
        raise SnapshotError("snapshot row counts do not match")
    object_bytes: dict[str, bytes] = {}
    objects = manifest.get("objects")
    if not isinstance(objects, list):
        raise SnapshotError("snapshot object manifest is invalid")
    object_members: set[str] = set()
    object_digests: list[str] = []
    for item in objects:
        if not isinstance(item, dict):
            raise SnapshotError("snapshot object entry is invalid")
        state = item.get("state")
        digest = item.get("digest")
        if not isinstance(digest, str) or state not in {
            "present",
            "missing",
            "retired",
        }:
            raise SnapshotError("snapshot object identity is invalid")
        object_digests.append(digest)
        if state == "present":
            member = item.get("member")
            if member != _member_name(digest) or member not in member_bytes:
                raise SnapshotError("snapshot present object is missing its bytes")
            data = member_bytes[member]
            if sha256_bytes(data) != digest or len(data) != item.get("byte_size"):
                raise SnapshotError(f"snapshot evidence failed verification: {digest}")
            object_bytes[digest] = data
            object_members.add(member)
        elif "member" in item:
            raise SnapshotError("snapshot tombstone unexpectedly contains bytes")
    canonical_digests = {
        str(row["digest"]) for row in records.get("evidence_object", [])
    }
    if len(object_digests) != len(set(object_digests)):
        raise SnapshotError("snapshot object manifest contains duplicate digests")
    if canonical_digests != set(object_digests):
        raise SnapshotError("snapshot object manifest does not match canonical records")
    if set(member_bytes) != {"records.json", "schema.json", *object_members}:
        raise SnapshotError("snapshot contains unreferenced object members")
    return SnapshotPayload(manifest, records, object_bytes)


def import_snapshot(
    payload: SnapshotPayload,
    memory_store: MemoryStore,
    evidence_store: EvidenceStore,
) -> dict[str, Any]:
    existing = memory_store.snapshot_records()
    if any(existing.values()):
        raise SnapshotError("snapshot import requires an empty canonical store")
    try:
        object_records = {
            str(row["digest"]): EvidenceObjectRecord(**row)
            for row in payload.records["evidence_object"]
        }
    except (KeyError, TypeError) as exc:
        raise SnapshotError("snapshot evidence object rows are invalid") from exc
    for digest, data in payload.object_bytes.items():
        try:
            expected = object_records[digest]
        except KeyError as exc:
            raise SnapshotError(
                f"snapshot object has no canonical record: {digest}"
            ) from exc
        evidence_store.put_bytes(data, expected)
    counts = memory_store.import_snapshot_records(payload.records)
    return {
        "imported": True,
        "row_counts": counts,
        "snapshot_id": payload.manifest["snapshot_id"],
    }
