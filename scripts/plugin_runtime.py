from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

APP_NAME = "analytical-memory"


def _data_root() -> Path:
    configured = os.getenv("ANALYTICAL_MEMORY_PLUGIN_DATA")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME
    base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def _configure_environment(data_root: Path) -> None:
    defaults = {
        "ANALYTICAL_MEMORY_DATA_ROOT": data_root,
        "ANALYTICAL_MEMORY_CATALOG": data_root / "memories.json",
        "ANALYTICAL_MEMORY_DB": data_root / "memory.db",
        "ANALYTICAL_MEMORY_EVIDENCE_ROOT": data_root / "evidence",
    }
    for name, value in defaults.items():
        if not os.environ.get(name):
            os.environ[name] = str(value)


def main() -> int:
    if sys.argv[1:] != ["serve"]:
        print("usage: plugin_runtime.py serve", file=sys.stderr)
        return 2

    data_root = _data_root()
    data_root.mkdir(parents=True, exist_ok=True)
    load_dotenv(data_root / ".env")
    _configure_environment(data_root)

    from analytical_memory.configuration import (
        build_application,
        environment_memory_catalog,
    )
    from analytical_memory.mcp_server import create_mcp_server
    from analytical_memory.memories import MemoryRouter

    application = build_application()
    application.initialize()
    router = MemoryRouter(application, environment_memory_catalog())
    create_mcp_server(application, router).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
