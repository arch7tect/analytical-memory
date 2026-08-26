from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analytical_memory.canonical import canonical_json, sha256_json


class SchemaCompilationError(ValueError):
    pass


def default_metadata_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "schema" / "metadata"


def default_output_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schema" / "current.json"


def _merge(target: dict[str, Any], fragment: dict[str, Any], source: Path) -> None:
    for key, value in fragment.items():
        if key in target:
            raise SchemaCompilationError(
                f"duplicate top-level schema key {key!r} in {source.name}"
            )
        target[key] = value


def compile_schema(metadata_directory: Path | None = None) -> dict[str, Any]:
    directory = metadata_directory or default_metadata_directory()
    files = sorted(directory.glob("*.json"), key=lambda item: item.name)
    if not files:
        raise SchemaCompilationError(f"no metadata fragments found in {directory}")
    document: dict[str, Any] = {}
    for source in files:
        try:
            fragment = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SchemaCompilationError(f"cannot load metadata: {source}") from exc
        if not isinstance(fragment, dict):
            raise SchemaCompilationError(f"metadata must be an object: {source}")
        _merge(document, fragment, source)
    document["schema_fingerprint"] = sha256_json(document)
    return document


def render_schema(metadata_directory: Path | None = None) -> str:
    compiled = compile_schema(metadata_directory)
    return json.dumps(compiled, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def schema_is_current(
    output: Path | None = None, metadata_directory: Path | None = None
) -> bool:
    target = output or default_output_path()
    try:
        existing = target.read_text(encoding="utf-8")
    except OSError:
        return False
    return existing == render_schema(metadata_directory)


def write_schema(
    output: Path | None = None, metadata_directory: Path | None = None
) -> dict[str, Any]:
    target = output or default_output_path()
    compiled = compile_schema(metadata_directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(compiled, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return compiled


def canonical_compiled_schema(metadata_directory: Path | None = None) -> str:
    return canonical_json(compile_schema(metadata_directory))
