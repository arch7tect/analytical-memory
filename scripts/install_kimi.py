"""Install this bundle's complete plugin into verified Kimi Code versions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

PLUGIN = "analytical-memory"
SUPPORTED_VERSIONS = {"0.39.1", "2.0.2"}
IGNORED = {".venv", "__pycache__", ".git", ".DS_Store", ".pytest_cache"}


def payload_files(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if IGNORED.intersection(relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError(f"plugin payload contains a symlink: {relative}")
        if path.is_file():
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


@contextmanager
def installation_lock(path: Path) -> Iterator[None]:
    # Keep the inode in place: closing releases the OS lock even after a crash.
    with path.open("a+b") as stream:
        try:
            if sys.platform == "win32":
                import msvcrt

                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("another Analytical Memory installer is running") from exc
        yield


def install(payload: Path, home: Path, *, kimi: str = "kimi") -> dict[str, Any]:
    version = subprocess.run(
        [kimi, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(
            f"Kimi {version}: unattended registration is verified only for "
            f"{sorted(SUPPORTED_VERSIONS)}; "
            "use the native /plugins install command instead"
        )
    payload = payload.resolve(strict=True)
    home = home.expanduser().resolve()
    if home.is_relative_to(payload):
        raise ValueError("Kimi home must be outside the source payload")
    manifest = json.loads((payload / "kimi.plugin.json").read_text())
    if manifest.get("name") != PLUGIN:
        raise ValueError("not an Analytical Memory Kimi bundle")
    server = manifest["mcpServers"][PLUGIN]
    if server.get("cwd") != "./" or manifest.get("skills") != "./skills/":
        raise ValueError("unsupported plugin layout")
    files = payload_files(payload)
    for required in (
        "pyproject.toml",
        "uv.lock",
        "scripts/plugin_runtime.py",
        "skills/analytical-memory/SKILL.md",
        "skills/analytical-memory-inspect/SKILL.md",
    ):
        if required not in files:
            raise ValueError(f"incomplete plugin: {required}")
    directory = home / "plugins"
    directory.mkdir(parents=True, exist_ok=True)
    registry = directory / "installed.json"
    if registry.is_symlink():
        raise ValueError("refusing a symlinked plugin registry")
    lock = directory / ".analytical-memory-install.lock"
    with installation_lock(lock):
        before = registry.read_bytes() if registry.exists() else None
        document: dict[str, Any] = (
            json.loads(before) if before is not None else {"version": 1, "plugins": []}
        )
        if (
            not isinstance(document, dict)
            or document.get("version") != 1
            or not isinstance(document.get("plugins"), list)
        ):
            raise ValueError("unsupported Kimi plugin registry")
        entries = document["plugins"]
        if any(
            not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
            for entry in entries
        ):
            raise ValueError("invalid plugin registry entry")
        matching = [entry for entry in entries if entry["id"] == PLUGIN]
        if len(matching) > 1:
            raise ValueError("duplicate Analytical Memory installation records")
        old = matching[0] if matching else {}
        if old and (
            not isinstance(old.get("root"), str) or not Path(old["root"]).is_absolute()
        ):
            raise ValueError("existing plugin root must be an absolute path string")
        root = Path(old["root"]) if old else None
        if (
            root is not None
            and root.is_dir()
            and payload_files(root) == files
            and old.get("enabled")
        ):
            return {
                "version": manifest["version"],
                "root": str(root),
                "registration": "unchanged",
                "activation": "pending host verification",
            }

        managed = directory / "managed"
        managed.mkdir(exist_ok=True)
        # A new directory preserves the previous installation and any local edits.
        target = Path(tempfile.mkdtemp(prefix=f"{PLUGIN}-", dir=managed))
        for relative in files:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(payload / relative, destination)
        if payload_files(target) != files:
            raise ValueError("plugin changed during copying; registry left unchanged")
        subprocess.run(
            [
                "uv",
                "sync",
                "--project",
                str(target),
                "--frozen",
                "--no-dev",
                "--no-editable",
                "--extra",
                "postgres",
                "--python",
                "3.12",
            ],
            check=True,
        )
        now = datetime.now(UTC).isoformat()
        entry = {
            **old,
            "id": PLUGIN,
            "root": str(target),
            "source": "local-path",
            "enabled": True,
            "installedAt": old.get("installedAt", now),
            "updatedAt": now,
            "originalSource": str(payload),
        }
        # A local bundle must not inherit an unrelated remote update source.
        entry.pop("github", None)
        document["plugins"] = [
            entry if item["id"] == PLUGIN else item for item in entries
        ]
        if not matching:
            document["plugins"].append(entry)
        if (registry.read_bytes() if registry.exists() else None) != before:
            raise ValueError("plugin registry changed concurrently; retry installation")
        if before is not None:
            backup = (
                directory / f"installed.before-analytical-memory-{uuid4().hex}.json"
            )
            with backup.open("xb") as stream:
                stream.write(before)
        temporary = directory / f".installed-{uuid4().hex}.tmp"
        try:
            with temporary.open("x") as stream:
                json.dump(document, stream, indent=2)
                stream.write("\n")
            if (registry.read_bytes() if registry.exists() else None) != before:
                raise ValueError(
                    "plugin registry changed concurrently; retry installation"
                )
            os.replace(temporary, registry)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "version": manifest["version"],
            "root": str(target),
            "registration": "installed",
            "activation": "restart Kimi or /reload, then call memory_discover",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        type=Path,
        default=Path(os.environ.get("KIMI_CODE_HOME", "~/.kimi-code")),
    )
    parser.add_argument("--kimi", default="kimi", help="Kimi Code executable")
    args = parser.parse_args()
    try:
        result = install(Path(__file__).resolve().parents[1], args.home, kimi=args.kimi)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
