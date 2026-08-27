from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tarfile
from pathlib import Path

import build_plugin_bundles as plugin_bundles

RELEASE_OUTPUT = plugin_bundles.ROOT / "dist" / "release"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive(source: Path, destination: Path, archive_root: str) -> None:
    with tarfile.open(destination, "w:gz") as archive:
        archive.add(source, arcname=archive_root)


def build_release(tag: str | None = None) -> list[Path]:
    version = plugin_bundles.project_version()
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"tag {tag!r} does not match project version v{version}")

    shutil.rmtree(RELEASE_OUTPUT, ignore_errors=True)
    RELEASE_OUTPUT.mkdir(parents=True)
    plugin_bundles.build_bundles()
    subprocess.run(
        ["uv", "build", "--out-dir", str(RELEASE_OUTPUT)],
        cwd=plugin_bundles.ROOT,
        check=True,
    )

    artifacts = [
        RELEASE_OUTPUT / f"analytical_memory-{version}.tar.gz",
        RELEASE_OUTPUT / f"analytical_memory-{version}-py3-none-any.whl",
    ]
    if not all(path.is_file() for path in artifacts):
        raise RuntimeError("uv build did not create the expected distributions")
    for host in ("claude", "kimi", "openai"):
        filename = f"{plugin_bundles.PLUGIN_NAME}-{version}-{host}.tar.gz"
        destination = RELEASE_OUTPUT / filename
        _archive(
            plugin_bundles.OUTPUT / host,
            destination,
            f"{plugin_bundles.PLUGIN_NAME}-{version}-{host}",
        )
        artifacts.append(destination)

    checksum_path = (
        RELEASE_OUTPUT / f"{plugin_bundles.PLUGIN_NAME}-{version}-SHA256SUMS"
    )
    checksum_path.write_text(
        "".join(
            f"{_sha256(path)}  {path.name}\n"
            for path in sorted(artifacts, key=lambda item: item.name)
        ),
        encoding="utf-8",
    )
    artifacts.append(checksum_path)
    return sorted(artifacts, key=lambda item: item.name)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Python distributions and host plugin release archives."
    )
    parser.add_argument("--tag", help="Require an exact v<project-version> tag")
    arguments = parser.parse_args()
    try:
        artifacts = build_release(arguments.tag)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        parser.error(str(exc))
    for artifact in artifacts:
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
