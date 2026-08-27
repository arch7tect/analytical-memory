from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def resource_path(*parts: str) -> Path:
    resource = files("analytical_memory").joinpath("resources", *parts)
    if not isinstance(resource, Path):
        raise RuntimeError("analytical-memory package resources are not file-backed")
    return resource


def source_checkout_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if not (root / "pyproject.toml").is_file():
        raise RuntimeError(
            "schema compilation is available only from a source checkout"
        )
    return root
