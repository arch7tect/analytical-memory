from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from analytical_memory.canonical import sha256_json, strict_json_loads
from analytical_memory.domain import JsonlImportRequest, JsonlScan
from analytical_memory.errors import ImportValidationError, ProhibitedContentError
from analytical_memory.limits import MAX_EVIDENCE_INGEST_BYTES, MAX_JSONL_LINE_BYTES

JSON_TYPES = {"string", "number", "boolean", "object", "array"}
PROHIBITED_FIELDS = {
    "api_key",
    "apikey",
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
}


def json_type(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise ImportValidationError("unsupported JSON value")


def normalize_declared_type(value: str) -> str:
    if value == "integer":
        return "number"
    if value not in JSON_TYPES:
        raise ImportValidationError(f"unsupported JSON type: {value}")
    return value


def split_entity_type(entity_type: str) -> tuple[str, str]:
    namespace, separator, name = entity_type.rpartition(".")
    if not separator or not namespace or not name:
        raise ImportValidationError("entity_type must be namespaced")
    validate_namespace(namespace)
    return namespace, name


def validate_namespace(namespace: str) -> str:
    if not namespace or any(
        not segment or segment.strip() != segment for segment in namespace.split(".")
    ):
        raise ImportValidationError(
            "namespace must contain non-empty dot-separated segments"
        )
    return namespace


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open("rb") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if len(raw) > MAX_JSONL_LINE_BYTES:
                raise ImportValidationError(f"line {line_number}: line is too large")
            if not raw.strip():
                continue
            if line_number == 1 and raw.startswith(b"\xef\xbb\xbf"):
                raise ImportValidationError("line 1: UTF-8 BOM is not allowed")
            try:
                value = strict_json_loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise ImportValidationError(
                    f"line {line_number}: invalid JSON"
                ) from exc
            if not isinstance(value, dict):
                raise ImportValidationError(
                    f"line {line_number}: each JSONL value must be an object"
                )
            yield line_number, value


def _key_tuple(
    request: JsonlImportRequest, record: dict[str, Any], line_number: int
) -> list[Any]:
    values: list[Any] = []
    for selector in request.key:
        if selector.field not in record or record[selector.field] is None:
            raise ImportValidationError(
                f"line {line_number}: key field {selector.field!r} is missing or null"
            )
        value = record[selector.field]
        actual = json_type(value)
        expected = normalize_declared_type(selector.type)
        if actual in {"array", "object"}:
            raise ImportValidationError(
                f"line {line_number}: key field {selector.field!r} must be scalar"
            )
        if actual != expected or (
            selector.type == "integer"
            and (isinstance(value, bool) or not isinstance(value, int))
        ):
            raise ImportValidationError(
                f"line {line_number}: key field {selector.field!r} has type {actual}, "
                f"expected {selector.type}"
            )
        values.append(value)
    return values


def scan_jsonl(request: JsonlImportRequest) -> JsonlScan:
    split_entity_type(request.entity_type)
    if not request.key:
        raise ImportValidationError("import key must contain at least one field")
    if len({item.field for item in request.key}) != len(request.key):
        raise ImportValidationError("import key fields must be unique")
    for item in request.key:
        normalize_declared_type(item.type)

    source_size = request.source_path.stat().st_size
    if source_size > MAX_EVIDENCE_INGEST_BYTES:
        raise ImportValidationError("JSONL source exceeds the ingest limit")

    descriptor, spool_name = tempfile.mkstemp(prefix="analytical-memory-jsonl-")
    os.close(descriptor)
    spool_path = Path(spool_name)
    key_db_path = spool_path.with_suffix(".keys.sqlite")
    hasher = hashlib.sha256()
    byte_size = 0
    try:
        with request.source_path.open("rb") as source, spool_path.open("wb") as target:
            while chunk := source.read(1_048_576):
                hasher.update(chunk)
                byte_size += len(chunk)
                target.write(chunk)

        connection = sqlite3.connect(key_db_path)
        try:
            connection.execute("PRAGMA temp_store = FILE")
            connection.execute(
                "CREATE TABLE import_key "
                "(key_hash TEXT PRIMARY KEY, line INTEGER NOT NULL)"
            )
            field_types: dict[str, str] = {}
            present_counts: dict[str, int] = {}
            null_fields: set[str] = set()
            record_count = 0
            for line_number, record in iter_jsonl(spool_path):
                record_count += 1
                prohibited = {
                    name for name in record if name.casefold() in PROHIBITED_FIELDS
                }
                if prohibited:
                    raise ProhibitedContentError(
                        f"line {line_number}: prohibited credential fields: "
                        f"{sorted(prohibited)}"
                    )
                key_hash = sha256_json(_key_tuple(request, record, line_number))
                try:
                    connection.execute(
                        "INSERT INTO import_key (key_hash, line) VALUES (?, ?)",
                        (key_hash, line_number),
                    )
                except sqlite3.IntegrityError as exc:
                    first = connection.execute(
                        "SELECT line FROM import_key WHERE key_hash = ?", (key_hash,)
                    ).fetchone()[0]
                    raise ImportValidationError(
                        f"line {line_number}: duplicate import key first seen "
                        f"on line {first}"
                    ) from exc
                for name, value in record.items():
                    present_counts[name] = present_counts.get(name, 0) + 1
                    actual = json_type(value)
                    if actual is None:
                        null_fields.add(name)
                        continue
                    previous = field_types.get(name)
                    if previous is not None and previous != actual:
                        raise ImportValidationError(
                            f"line {line_number}: field {name!r} mixes "
                            f"{previous} and {actual}"
                        )
                    field_types[name] = actual
            connection.commit()
        finally:
            connection.close()
        return JsonlScan(
            spool_path=spool_path,
            content_hash=hasher.hexdigest(),
            byte_size=byte_size,
            record_count=record_count,
            field_types=field_types,
            present_counts=present_counts,
            null_fields=frozenset(null_fields),
        )
    except Exception:
        spool_path.unlink(missing_ok=True)
        raise
    finally:
        key_db_path.unlink(missing_ok=True)


def import_idempotency_key(request: JsonlImportRequest, content_hash: str) -> str:
    return sha256_json(
        {
            "content_hash": content_hash,
            "entity_type": request.entity_type,
            "key": [{"field": item.field, "type": item.type} for item in request.key],
        }
    )
