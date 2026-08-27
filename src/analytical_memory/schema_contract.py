from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from analytical_memory.canonical import sha256_json
from analytical_memory.resources import resource_path


class SchemaContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SchemaContract:
    document: dict[str, Any]
    fingerprint: str


def default_schema_path() -> Path:
    return resource_path("schema", "current.json")


def load_schema(path: Path | None = None) -> SchemaContract:
    schema_path = path or default_schema_path()
    try:
        document = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaContractError(f"cannot load schema: {schema_path}") from exc
    if not isinstance(document, dict):
        raise SchemaContractError("schema document must be an object")
    declared = document.get("schema_fingerprint")
    if not isinstance(declared, str):
        raise SchemaContractError("schema_fingerprint must be a string")
    fingerprint_input = dict(document)
    fingerprint_input.pop("schema_fingerprint")
    computed = sha256_json(fingerprint_input)
    if declared != computed:
        raise SchemaContractError(
            f"schema fingerprint mismatch: declared={declared} computed={computed}"
        )
    return SchemaContract(document=document, fingerprint=computed)
