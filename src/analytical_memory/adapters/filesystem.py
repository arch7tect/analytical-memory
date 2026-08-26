from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path

from analytical_memory.canonical import sha256_bytes
from analytical_memory.domain import EvidenceObjectRecord, EvidenceStatus
from analytical_memory.ports import EvidenceStore


class FileEvidenceStore(EvidenceStore):
    def __init__(self, root: Path) -> None:
        self.root = root

    def initialize(self) -> None:
        (self.root / "objects" / "sha256").mkdir(parents=True, exist_ok=True)
        (self.root / ".tmp").mkdir(parents=True, exist_ok=True)

    def object_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError("digest must be lowercase SHA-256 hex")
        return self.root / "objects" / "sha256" / digest[:2] / digest

    def put(self, source: Path, expected: EvidenceObjectRecord) -> EvidenceStatus:
        self.initialize()
        data = source.read_bytes()
        digest = sha256_bytes(data)
        if digest != expected.digest or len(data) != expected.byte_size:
            raise ValueError("evidence changed after planning")
        destination = self.object_path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            status = self.stat(digest)
            if status.verification != "verified":
                raise ValueError("existing evidence object failed verification")
            return status

        file_descriptor, temporary_name = tempfile.mkstemp(dir=self.root / ".tmp")
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o600)
            with suppress(FileExistsError):
                os.link(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
        return self.stat(digest)

    def stat(self, digest: str) -> EvidenceStatus:
        path = self.object_path(digest)
        if not path.is_file():
            return EvidenceStatus(
                availability="missing",
                verification="unverified",
                digest=digest,
                byte_size=None,
            )
        data = path.read_bytes()
        actual = sha256_bytes(data)
        return EvidenceStatus(
            availability="present",
            verification="verified" if actual == digest else "corrupt",
            digest=digest,
            byte_size=len(data),
        )
