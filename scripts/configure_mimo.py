"""Configure or check a generic plugin in a MiMo Code project without an MCP client."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

SKILLS = ("analytical-memory", "analytical-memory-inspect")


def configuration(payload: Path, data_root: Path | None = None) -> dict[str, Any]:
    payload = payload.resolve(strict=True)
    manifest = json.loads((payload / ".mcp.json").read_text(encoding="utf-8"))
    server = manifest["mcpServers"]["analytical-memory"]
    arguments = [str(payload) if value == "." else value for value in server["args"]]
    arguments[arguments.index("scripts/plugin_runtime.py")] = str(
        payload / "scripts" / "plugin_runtime.py"
    )
    for name in SKILLS:
        if not (payload / "skills" / name / "SKILL.md").is_file():
            raise ValueError(f"plugin is missing skill: {name}")
    entry: dict[str, Any] = {
        "type": "local",
        "command": [server["command"], *arguments],
        "timeout": 600_000,
        "enabled": True,
    }
    if data_root is not None:
        entry["environment"] = {
            "ANALYTICAL_MEMORY_PLUGIN_DATA": str(data_root.expanduser().resolve())
        }
    return {
        "$schema": "https://mimo.xiaomi.com/mimocode/config.json",
        "skills": {"paths": [str(payload / "skills")]},
        "mcp": {"analytical-memory": entry},
    }


def configure(workspace: Path, document: dict[str, Any]) -> Path:
    workspace = workspace.expanduser().resolve()
    output = workspace / ".mimocode" / "mimocode.jsonc"
    alternatives = (
        workspace / "mimocode.json",
        workspace / "mimocode.jsonc",
        workspace / ".mimocode" / "mimocode.json",
    )
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError("refusing a linked project configuration directory or file")
    if any(path.exists() or path.is_symlink() for path in alternatives):
        raise ValueError("project has another config; merge --print settings into it")
    encoded = json.dumps(document, indent=2) + "\n"
    if output.exists():
        if output.read_text(encoding="utf-8") != encoded:
            raise ValueError(
                "existing config preserved; merge --print settings into it"
            )
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    return output


def host_output(cli: str, workspace: Path, *args: str) -> str:
    result = subprocess.run(
        [cli, *args], cwd=workspace, capture_output=True, text=True, timeout=180
    )
    if result.returncode:
        # Host diagnostics may contain complete skills or settings. Do not echo them.
        raise ValueError(f"MiMo {' '.join(args)} failed (exit {result.returncode})")
    return result.stdout


def check_host(cli: str, workspace: Path, payload: Path) -> dict[str, Any]:
    resolved = json.loads(host_output(cli, workspace, "debug", "config"))
    servers = resolved.get("mcp", {}) if isinstance(resolved, dict) else {}
    expected_command = configuration(payload)["mcp"]["analytical-memory"]["command"]
    server = servers.get("analytical-memory") if isinstance(servers, dict) else None
    if (
        not isinstance(server, dict)
        or server.get("type") != "local"
        or server.get("enabled") is False
        or server.get("command") != expected_command
    ):
        raise ValueError("MiMo must use this bundle's enabled MCP launch command")
    if any(
        name != "analytical-memory"
        and isinstance(entry, dict)
        and entry.get("enabled", True)
        and entry.get("command") == expected_command
        for name, entry in servers.items()
    ):
        raise ValueError("MiMo has a duplicate connection to this plugin")
    skills = json.loads(host_output(cli, workspace, "debug", "skill"))
    if not isinstance(skills, list):
        raise ValueError("MiMo returned an unsupported skill inventory")
    for name in SKILLS:
        expected = (payload / "skills" / name / "SKILL.md").resolve()
        matches = [s for s in skills if isinstance(s, dict) and s.get("name") == name]
        if len(matches) != 1 or not isinstance(matches[0].get("location"), str):
            raise ValueError(f"MiMo must discover exactly one {name} skill")
        if Path(matches[0]["location"]).resolve() != expected:
            raise ValueError(f"MiMo resolved {name} from another installation")
    status = host_output(cli, workspace, "mcp", "list")
    status = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", status)
    lines = [
        line
        for line in status.splitlines()
        if re.match(r"^[\s│●✓✔├└─]*analytical-memory\s+", line)
    ]
    if len(lines) != 1 or not re.search(r"\banalytical-memory\s+connected\b", lines[0]):
        raise ValueError("MiMo does not report one connected analytical-memory server")
    return {
        "skills": {name: "available" for name in SKILLS},
        "mcp": "connected",
        "readiness": "pending native memory_discover in the reloaded conversation",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--data-root", type=Path, default=os.getenv("ANALYTICAL_MEMORY_PLUGIN_DATA")
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check", action="store_true", help="Check through native MiMo CLI only"
    )
    action.add_argument(
        "--print",
        dest="print_settings",
        action="store_true",
        help="Print settings for a manual merge",
    )
    parser.add_argument("--mimo", default="mimo", help="MiMo executable")
    args = parser.parse_args()
    payload = Path(__file__).resolve().parents[1]
    try:
        if args.check:
            print(json.dumps(check_host(args.mimo, args.workspace.resolve(), payload)))
        else:
            document = configuration(payload, args.data_root)
            if args.print_settings:
                print(json.dumps(document, indent=2))
            else:
                output = configure(args.workspace, document)
                print(f"Configured both plugin skills and MCP: {output}")
                print(
                    "Reload MiMo, keeping this conversation. Verify readiness with "
                    "native memory_discover; do not create an MCP client."
                )
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
