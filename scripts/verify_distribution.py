from __future__ import annotations

import argparse
import getpass
import json
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_WHEEL_SUFFIXES = (
    "analytical_memory/sqlite_migrations.py",
    "analytical_memory/postgresql_migrations.py",
    "analytical_memory/resources/schema/current.json",
    "analytical_memory/resources/schema/query-ir-contract.json",
    "analytical_memory/resources/migrations/sqlite/manifest.json",
    "analytical_memory/resources/migrations/postgresql/manifest.json",
    "analytical_memory/resources/examples/quickstart/query.json",
)


def _members(artifact: Path) -> list[tuple[str, bytes]]:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            return [(name, archive.read(name)) for name in archive.namelist()]
    with tarfile.open(artifact, "r:gz") as archive:
        members = []
        for member in archive.getmembers():
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is not None:
                    members.append((member.name, stream.read()))
        return members


def _scan(artifact: Path) -> list[str]:
    problems: list[str] = []
    members = _members(artifact)
    names = [name for name, _ in members]
    for name in names:
        basename = Path(name).name
        if (
            basename == ".env"
            or (basename.startswith(".env.") and basename != ".env.template")
            or basename in {"id_rsa", "id_ed25519", "id_ecdsa", "credentials"}
        ):
            problems.append(f"prohibited file: {name}")
        if basename.endswith((".pem", ".key", ".p12", ".pfx")):
            problems.append(f"credential-like file: {name}")
    home = str(Path.home())
    username = getpass.getuser()
    markers = (
        home,
        "/" + "Users" + "/",
        "/" + "home" + "/",
        "BEGIN " + "PRIVATE KEY",
    )
    for name, data in members:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for marker in markers:
            if marker and marker in text:
                problems.append(f"prohibited text marker {marker!r}: {name}")
        if username and f"/{username}/" in text:
            problems.append(f"developer username path: {name}")
    if artifact.suffix == ".whl":
        for suffix in REQUIRED_WHEEL_SUFFIXES:
            if not any(name.endswith(suffix) for name in names):
                problems.append(f"wheel resource missing: {suffix}")
    return problems


def _run_installed(uv: str, artifact: Path, root: Path) -> None:
    environment = root / artifact.name.replace(".", "-")
    subprocess.run([uv, "venv", str(environment)], check=True)
    python = environment / "bin" / "python"
    subprocess.run(
        [uv, "pip", "install", "--python", str(python), str(artifact)], check=True
    )
    subprocess.run(
        [str(environment / "bin" / "memory-quickstart")],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [str(environment / "bin" / "memory"), "schema", "show"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required")
    with tempfile.TemporaryDirectory(prefix="analytical-memory-dist-") as raw:
        root = Path(raw)
        output = root / "dist"
        subprocess.run(
            [uv, "build", "--out-dir", str(output)],
            cwd=REPOSITORY_ROOT,
            check=True,
        )
        artifacts = sorted(
            artifact
            for artifact in output.iterdir()
            if artifact.is_file() and artifact.suffix in {".gz", ".whl"}
        )
        if len(artifacts) != 2 or not any(
            artifact.suffix == ".whl" for artifact in artifacts
        ):
            raise RuntimeError("expected one wheel and one source distribution")
        problems = [problem for artifact in artifacts for problem in _scan(artifact)]
        if problems:
            raise RuntimeError(
                "distribution safety check failed: " + "; ".join(problems)
            )
        install_root = root / "install"
        install_root.mkdir()
        for artifact in artifacts:
            _run_installed(uv, artifact, install_root)
        print(
            json.dumps(
                {
                    "artifacts": [artifact.name for artifact in artifacts],
                    "installed": len(artifacts),
                    "safe": True,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
