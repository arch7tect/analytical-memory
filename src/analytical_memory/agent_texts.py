from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from typing import Any

from analytical_memory.resources import resource_path


@lru_cache(maxsize=1)
def _document() -> dict[str, Any]:
    value = json.loads(resource_path("agent", "texts.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("agent texts resource must contain a JSON object")
    return value


def _value(*path: str) -> Any:
    value: Any = _document()
    for component in path:
        if not isinstance(value, dict) or component not in value:
            location = ".".join(path)
            raise RuntimeError(f"agent text {location!r} is missing")
        value = value[component]
    return value


def agent_text(*path: str) -> str:
    value = _value(*path)
    if not isinstance(value, str) or not value:
        location = ".".join(path)
        raise RuntimeError(f"agent text {location!r} must be a non-empty string")
    return value


def agent_document(*path: str) -> dict[str, Any]:
    value = _value(*path)
    if not isinstance(value, dict):
        location = ".".join(path)
        raise RuntimeError(f"agent document {location!r} must be a JSON object")
    return deepcopy(value)
