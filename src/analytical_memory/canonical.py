from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

UUID_NAMESPACE = uuid.UUID("e586f762-61e8-5df7-a6a5-8443ff7ac9fb")


def strict_json_loads(value: str | bytes | bytearray) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = item
        return result

    def reject_constant(constant: str) -> Any:
        raise ValueError(f"non-finite JSON number: {constant}")

    return json.loads(
        value,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def stable_uuid(kind: str, *parts: object) -> str:
    payload = canonical_json([kind, *parts])
    return str(uuid.uuid5(UUID_NAMESPACE, payload))


def normalize_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a UTC offset")
    normalized = parsed.astimezone(UTC).isoformat(timespec="seconds")
    return normalized.replace("+00:00", "Z")


def canonical_text_key(value: str | None) -> tuple[int, str, str]:
    if value is None:
        return (0, "", "")
    return (1, value.casefold(), value)
