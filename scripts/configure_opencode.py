"""Connect one unpacked plugin's skills and server to an OpenCode project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def configuration(payload: Path, data_root: Path | None = None) -> dict[str, Any]:
    payload = payload.resolve(strict=True)
    document = json.loads((payload / ".mcp.json").read_text(encoding="utf-8"))
    server = document["mcpServers"]["analytical-memory"]
    arguments = [str(payload) if value == "." else value for value in server["args"]]
    runtime = arguments.index("scripts/plugin_runtime.py")
    arguments[runtime] = str(payload / arguments[runtime])
    skill_root = payload / "skills"
    if not all(
        (skill_root / name / "SKILL.md").is_file()
        for name in ("analytical-memory", "analytical-memory-inspect")
    ):
        raise ValueError("plugin is missing its shared skills")
    entry = {
        "type": "local",
        "command": [server["command"], *arguments],
        "cwd": str(payload),
        "timeout": {"startup": 120_000, "catalog": 120_000, "execution": 600_000},
    }
    if data_root is not None:
        entry["environment"] = {
            "ANALYTICAL_MEMORY_PLUGIN_DATA": str(data_root.expanduser().resolve())
        }
    return {
        "$schema": "https://opencode.ai/config.json",
        "skills": [str(skill_root)],
        "mcp": {"servers": {"analytical-memory": entry}},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Create a new OpenCode config file")
    parser.add_argument("--data-root", type=Path, help="Override plugin data directory")
    args = parser.parse_args()
    payload = Path(__file__).resolve().parents[1]
    try:
        result = configuration(payload, args.data_root)
        encoded = json.dumps(result, indent=2) + "\n"
        if args.output is None:
            print(encoded, end="")
        else:
            output = args.output.expanduser().resolve()
            alternative = output.with_suffix(
                ".json" if output.suffix == ".jsonc" else ".jsonc"
            )
            nested_configs = (
                output.parent / ".opencode" / "opencode.json",
                output.parent / ".opencode" / "opencode.jsonc",
            )
            if alternative.exists() or any(path.exists() for path in nested_configs):
                raise ValueError("project has another config; merge printed settings")
            if output.exists():
                if output.read_text(encoding="utf-8") != encoded:
                    raise ValueError(
                        f"refusing to replace {output}; omit --output to print "
                        "settings and merge them into your existing configuration"
                    )
            else:
                if output.with_suffix(".jsonc").exists():
                    raise ValueError(
                        "project has a JSONC config; merge printed settings"
                    )
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("x", encoding="utf-8") as stream:
                    stream.write(encoded)
            print(f"Configured plugin skills and server: {output}")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
