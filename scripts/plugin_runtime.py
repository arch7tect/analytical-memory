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


def main() -> int:
    if sys.argv[1:] != ["serve"]:
        print("usage: plugin_runtime.py serve", file=sys.stderr)
        return 2

    data_root = _data_root()
    data_root.mkdir(parents=True, exist_ok=True)
    load_dotenv(data_root / ".env")
    os.environ.setdefault("ANALYTICAL_MEMORY_DB", str(data_root / "memory.db"))
    os.environ.setdefault(
        "ANALYTICAL_MEMORY_EVIDENCE_ROOT", str(data_root / "evidence")
    )

    from analytical_memory.configuration import build_application
    from analytical_memory.mcp_server import create_mcp_server

    application = build_application()
    application.initialize()
    create_mcp_server(application).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
