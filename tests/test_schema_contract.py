from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from analytical_memory.schema_contract import SchemaContractError, load_schema

from .conftest import REPOSITORY_ROOT


def _read_schema() -> dict[str, Any]:
    value = json.loads(
        (REPOSITORY_ROOT / "schema" / "current.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return value


def test_current_schema_fingerprint_is_self_consistent() -> None:
    schema = load_schema(REPOSITORY_ROOT / "schema" / "current.json")
    assert schema.fingerprint == schema.document["schema_fingerprint"]


def test_schema_loader_rejects_tampered_document(tmp_path: Path) -> None:
    document = _read_schema()
    document["ontology_version"] = "changed-without-new-fingerprint"
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(SchemaContractError, match="fingerprint mismatch"):
        load_schema(path)
