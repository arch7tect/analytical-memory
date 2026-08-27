from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from analytical_memory.canonical import sha256_bytes, strict_json_loads
from analytical_memory.errors import StoreNotInitializedError
from analytical_memory.version import __version__

MIGRATION_TOOL_VERSION = __version__


@dataclass(frozen=True, slots=True)
class MigrationDefinition:
    version: int
    file: str
    checksum: str
    target_fingerprint: str


@dataclass(frozen=True, slots=True)
class MigrationManifest:
    backend_profile: str
    schema_version: int
    migrations: tuple[MigrationDefinition, ...]


def load_migration_manifest(
    directory: Path, *, backend_profile: str
) -> MigrationManifest:
    manifest_path = directory / "manifest.json"
    try:
        payload = strict_json_loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoreNotInitializedError(
            f"cannot load {backend_profile} migration manifest"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("backend_profile") != backend_profile
        or not isinstance(payload.get("migrations"), list)
        or not payload["migrations"]
    ):
        raise StoreNotInitializedError(f"invalid {backend_profile} migration manifest")
    definitions: list[MigrationDefinition] = []
    try:
        for raw in payload["migrations"]:
            if not isinstance(raw, dict):
                raise TypeError
            definition = MigrationDefinition(
                version=int(raw["version"]),
                file=str(raw["file"]),
                checksum=str(raw["checksum"]),
                target_fingerprint=str(raw["target_fingerprint"]),
            )
            source = directory / definition.file
            actual = sha256_bytes(source.read_bytes())
            if actual != definition.checksum:
                raise StoreNotInitializedError(
                    f"{backend_profile} migration checksum mismatch: {definition.file}"
                )
            definitions.append(definition)
        schema_version = int(payload.get("schema_version", definitions[-1].version))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise StoreNotInitializedError(
            f"invalid {backend_profile} migration manifest"
        ) from exc
    versions = [item.version for item in definitions]
    expected_versions = list(range(versions[0], versions[0] + len(versions)))
    if versions != expected_versions or schema_version != versions[-1]:
        raise StoreNotInitializedError(
            f"{backend_profile} migrations must be contiguous and ordered"
        )
    return MigrationManifest(
        backend_profile=backend_profile,
        schema_version=schema_version,
        migrations=tuple(definitions),
    )
