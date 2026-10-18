from __future__ import annotations

import json
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

PLUGIN_NAME = "analytical-memory"
MARKETPLACE_NAME = "analytical-memory-local"
ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dist" / "plugins"
HOSTS = ("claude", "kimi", "openai", "generic")
REPOSITORY_DOCS = {
    "archive",
    "decisions",
    "proposals",
    "backlog.md",
    "implementation-plan.md",
    "native-analytics-delivery.md",
}
REPOSITORY_URL = "https://github.com/arch7tect/analytical-memory/blob/main/"
DOCUMENT_LINK = re.compile(
    r"(?P<prefix>\]\(|^ {0,3}\[[^\]\n]+\]:\s*)(?P<target>[^\s)]+)", re.MULTILINE
)


def _link_repository_docs(destination: Path) -> None:
    for source in destination.rglob("*.md"):

        def replace_link(match: re.Match[str], source: Path = source) -> str:
            target = match["target"]
            url = urlsplit(target.strip("<>"))
            if url.scheme or url.netloc or not url.path:
                return match[0]
            resolved = (source.parent / unquote(url.path)).resolve()
            if not resolved.is_relative_to(destination):
                return match[0]
            relative = resolved.relative_to(destination)
            if (
                len(relative.parts) < 2
                or relative.parts[0] != "docs"
                or relative.parts[1] not in REPOSITORY_DOCS
            ):
                return match[0]
            suffix = ("?" + url.query if url.query else "") + (
                "#" + url.fragment if url.fragment else ""
            )
            link = REPOSITORY_URL + relative.as_posix() + suffix
            if target.startswith("<"):
                link = "<" + link + ">"
            return match["prefix"] + link

        text = source.read_text(encoding="utf-8")
        linked = DOCUMENT_LINK.sub(replace_link, text)
        if linked != text:
            source.write_text(linked, encoding="utf-8")


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
    for name in (
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "compose.yaml",
        "LICENSE",
    ):
        shutil.copy2(ROOT / name, destination / name)

    def ignore_repository_docs(directory: str, names: list[str]) -> set[str]:
        excluded = {".DS_Store"}
        if Path(directory) == ROOT / "docs":
            excluded.update(REPOSITORY_DOCS)
        return excluded.intersection(names)

    shutil.copytree(ROOT / "docs", destination / "docs", ignore=ignore_repository_docs)
    shutil.copytree(ROOT / "examples", destination / "examples")
    (destination / "scripts").mkdir()
    shutil.copy2(
        ROOT / "scripts" / "plugin_runtime.py",
        destination / "scripts" / "plugin_runtime.py",
    )
    if host == "kimi":
        shutil.copy2(
            ROOT / "scripts" / "install_kimi.py",
            destination / "scripts" / "install_kimi.py",
        )
    if host == "generic":
        for name in ("configure_opencode.py", "configure_mimo.py"):
            shutil.copy2(ROOT / "scripts" / name, destination / "scripts" / name)
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
    _link_repository_docs(destination.resolve())


def _server(host: str) -> dict[str, Any]:
    if host == "claude":
        project = "${CLAUDE_PLUGIN_ROOT}"
        runtime = "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_runtime.py"
        server: dict[str, Any] = {"command": "uv"}
    else:
        project = "."
        runtime = "scripts/plugin_runtime.py"
        server = {"command": "uv", "cwd": "./" if host == "kimi" else "."}
    server["args"] = [
        "run",
        "--project",
        project,
        "--frozen",
        "--no-dev",
        "--no-editable",
        "--extra",
        "postgres",
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


def _build_generic(output: Path, version: str) -> None:
    plugin = output / "generic" / PLUGIN_NAME
    _copy_payload(plugin, host="generic")
    _write_json(
        plugin / "plugin.json",
        {
            **_common_manifest(version),
            "skills": "./skills/",
            "mcpServers": "./.mcp.json",
        },
    )
    _write_json(plugin / ".mcp.json", _server("generic"))


def build_bundles(output: Path = OUTPUT) -> None:
    for host in HOSTS:
        shutil.rmtree(output / host, ignore_errors=True)
    version = project_version()
    _build_claude(output, version)
    _build_kimi(output, version)
    _build_openai(output, version)
    _build_generic(output, version)
    for host in HOSTS:
        payload = (
            "plugins/analytical-memory" if host == "openai" else "analytical-memory"
        )
        (output / host / "README.md").write_text(
            "# Analytical Memory bundle\n\n"
            f"**MiMo Code:** start with the [short MiMo installation guide]"
            f"({payload}/docs/install-mimo.md).\n\n"
            f"[Plugin installation]({payload}/docs/plugin-installation.md) "
            "is the installation entry point for people and assistants. "
            "The plugin includes its skills and MCP server.\n\n"
            f"[Generic environments / OpenCode]({payload}/docs/"
            "plugin-installation.md#generic-environments-opencode) explains "
            "how to connect both components in other hosts.\n\n"
            f"[Quickstart for people]({payload}/docs/getting-started.md) shows "
            "prompts, expected answers, and the evolving structure.\n\n"
            f"The application payload is `{payload}/`: it contains `pyproject.toml`, "
            "`uv.lock`, `src/`, `docs/`, and `examples/`. Run application commands "
            "from that directory, not this marketplace root.\n",
            encoding="utf-8",
        )


def main() -> None:
    build_bundles()
    print(f"Built Claude, Kimi, Codex, and generic plugins in {OUTPUT}")


if __name__ == "__main__":
    main()
