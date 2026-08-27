from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from analytical_memory.schema_compiler import (
    SchemaCompilationError,
    compile_schema,
    render_schema,
    schema_is_current,
)
from analytical_memory.schema_contract import (
    SchemaContractError,
    default_schema_path,
    load_schema,
)


def _read_schema() -> dict[str, Any]:
    value = json.loads(default_schema_path().read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_current_schema_fingerprint_is_self_consistent() -> None:
    schema = load_schema(default_schema_path())
    assert schema.fingerprint == schema.document["schema_fingerprint"]


def test_schema_loader_rejects_tampered_document(tmp_path: Path) -> None:
    document = _read_schema()
    document["ontology_version"] = "changed-without-new-fingerprint"
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SchemaContractError, match="fingerprint mismatch"):
        load_schema(path)


def test_compiler_reproduces_current_schema() -> None:
    assert schema_is_current()
    compiled = compile_schema()
    current = _read_schema()
    assert compiled == current
    assert render_schema() == default_schema_path().read_text(encoding="utf-8")


def test_compiler_rejects_duplicate_top_level_keys(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    (metadata / "one.json").write_text('{"record_types": []}', encoding="utf-8")
    (metadata / "two.json").write_text('{"record_types": []}', encoding="utf-8")

    with pytest.raises(SchemaCompilationError, match="duplicate top-level"):
        compile_schema(metadata)
