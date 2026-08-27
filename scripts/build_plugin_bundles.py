from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path
from typing import Any

PLUGIN_NAME = "analytical-memory"
MARKETPLACE_NAME = "analytical-memory-local"
ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dist" / "plugins"


def project_version() -> str:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = document["project"]["version"]
    if not isinstance(version, str) or not version:
        raise RuntimeError("pyproject.toml has no project version")
    return version


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _copy_payload(destination: Path, *, host: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE"):
        shutil.copy2(ROOT / name, destination / name)
    (destination / "scripts").mkdir()
    shutil.copy2(
        ROOT / "scripts" / "plugin_runtime.py",
        destination / "scripts" / "plugin_runtime.py",
    )
    shutil.copytree(
        ROOT / "src" / "analytical_memory",
        destination / "src" / "analytical_memory",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )

    def ignore_host_metadata(directory: str, names: list[str]) -> set[str]:
        if host != "openai" and Path(directory).name == "agents":
            return {"openai.yaml"} & set(names)
        return set()

    shutil.copytree(
        ROOT / "plugin" / "skills",
        destination / "skills",
        ignore=ignore_host_metadata,
    )


def _server(host: str) -> dict[str, Any]:
    if host == "claude":
        project = "${CLAUDE_PLUGIN_ROOT}"
        runtime = "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_runtime.py"
        server: dict[str, Any] = {"command": "uv"}
    else:
        project = "."
        runtime = "scripts/plugin_runtime.py"
        server = {"command": "uv", "cwd": "."}
    server["args"] = [
        "run",
        "--project",
        project,
        "--frozen",
        "--no-dev",
        "--no-editable",
        "--python",
        "3.12",
        "python",
        "-I",
        runtime,
        "serve",
    ]
    if host == "openai":
        server["startup_timeout_sec"] = 120
    return {"mcpServers": {PLUGIN_NAME: server}}


def _common_manifest(version: str) -> dict[str, Any]:
    return {
        "name": PLUGIN_NAME,
        "version": version,
        "description": "Dynamic analytical memory with a discoverable ontology",
        "author": {
            "name": "Analytical Memory contributors",
            "url": "https://github.com/arch7tect/analytical-memory",
        },
        "homepage": "https://github.com/arch7tect/analytical-memory",
        "repository": "https://github.com/arch7tect/analytical-memory",
        "license": "Apache-2.0",
        "keywords": ["memory", "ontology", "mcp", "analytics"],
    }


def _build_claude(output: Path, version: str) -> None:
    root = output / "claude"
    plugin = root / PLUGIN_NAME
    _copy_payload(plugin, host="claude")
    _write_json(plugin / ".claude-plugin" / "plugin.json", _common_manifest(version))
    _write_json(plugin / ".mcp.json", _server("claude"))
    _write_json(
        root / ".claude-plugin" / "marketplace.json",
        {
            "name": MARKETPLACE_NAME,
            "description": "Local Analytical Memory plugins",
            "owner": {"name": "Analytical Memory contributors"},
            "plugins": [
                {
                    **_common_manifest(version),
                    "source": f"./{PLUGIN_NAME}",
                    "category": "development",
                    "tags": ["memory", "ontology", "mcp"],
                }
            ],
        },
    )


def _build_kimi(output: Path, version: str) -> None:
    root = output / "kimi"
    plugin = root / PLUGIN_NAME
    _copy_payload(plugin, host="kimi")
    manifest = {
        **_common_manifest(version),
        "author": "Analytical Memory contributors",
        "skills": "./skills/",
        "mcpServers": _server("kimi")["mcpServers"],
        "interface": {
            "displayName": "Analytical Memory",
            "shortDescription": "Query an evolving local memory",
            "longDescription": (
                "Import JSONL, connect entities, inspect the current ontology, "
                "and run relational or graph queries."
            ),
            "developerName": "Analytical Memory contributors",
            "websiteURL": "https://github.com/arch7tect/analytical-memory",
        },
    }
    manifest.pop("repository")
    _write_json(plugin / "kimi.plugin.json", manifest)
    _write_json(
        root / "marketplace.json",
        {
            "version": "2",
            "plugins": [
                {
                    "id": PLUGIN_NAME,
                    "displayName": "Analytical Memory",
                    "source": f"./{PLUGIN_NAME}",
                }
            ],
        },
    )


def _build_openai(output: Path, version: str) -> None:
    root = output / "openai"
    plugin = root / "plugins" / PLUGIN_NAME
    _copy_payload(plugin, host="openai")
    manifest = {
        **_common_manifest(version),
        "skills": "./skills/",
        "mcpServers": "./.mcp.json",
        "interface": {
            "displayName": "Analytical Memory",
            "shortDescription": "Query an evolving local memory",
            "longDescription": (
                "Import JSONL, connect entities, inspect the current ontology, "
                "and run relational or graph queries."
            ),
            "developerName": "Analytical Memory contributors",
            "category": "Developer Tools",
            "capabilities": ["Read", "Write"],
            "websiteURL": "https://github.com/arch7tect/analytical-memory",
            "defaultPrompt": [
                "Show the current memory ontology",
                "Import this JSONL dataset into memory",
                "Query the connected datasets",
            ],
        },
    }
    _write_json(plugin / ".codex-plugin" / "plugin.json", manifest)
    _write_json(plugin / ".mcp.json", _server("openai"))
    _write_json(
        root / ".agents" / "plugins" / "marketplace.json",
        {
            "name": MARKETPLACE_NAME,
            "interface": {"displayName": "Analytical Memory Local"},
            "plugins": [
                {
                    "name": PLUGIN_NAME,
                    "source": {
                        "source": "local",
                        "path": f"./plugins/{PLUGIN_NAME}",
                    },
                    "policy": {
                        "installation": "AVAILABLE",
                        "authentication": "ON_INSTALL",
                    },
                    "category": "Engineering",
                }
            ],
        },
    )


def build_bundles(output: Path = OUTPUT) -> None:
    for host in ("claude", "kimi", "openai"):
        shutil.rmtree(output / host, ignore_errors=True)
    version = project_version()
    _build_claude(output, version)
    _build_kimi(output, version)
    _build_openai(output, version)


def main() -> None:
    build_bundles()
    print(f"Built Claude, Kimi, and Codex plugins in {OUTPUT}")


if __name__ == "__main__":
    main()
