from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path

from analytical_memory.canonical import sha256_bytes
from analytical_memory.domain import (
    EvidenceObjectRecord,
    EvidencePutResult,
    EvidenceStatus,
    EvidenceStoreStatus,
)
from analytical_memory.limits import MAX_EVIDENCE_INGEST_BYTES
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
        return self.put_tracked(source, expected).status

    def put_tracked(
        self, source: Path, expected: EvidenceObjectRecord
    ) -> EvidencePutResult:
        if source.stat().st_size > MAX_EVIDENCE_INGEST_BYTES:
            raise ValueError("evidence object exceeds the local ingest limit")
        self.initialize()
        destination = self.object_path(expected.digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            status = self.stat(expected.digest)
            if (
                status.verification != "verified"
                or status.byte_size != expected.byte_size
            ):
                raise ValueError("existing evidence object failed verification")
            return EvidencePutResult(status=status, created=False)

        file_descriptor, temporary_name = tempfile.mkstemp(dir=self.root / ".tmp")
        temporary_path = Path(temporary_name)
        hasher = hashlib.sha256()
        byte_size = 0
        created = False
        try:
            with (
                source.open("rb") as input_stream,
                os.fdopen(file_descriptor, "wb") as output_stream,
            ):
                while chunk := input_stream.read(1_048_576):
                    hasher.update(chunk)
                    byte_size += len(chunk)
                    output_stream.write(chunk)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            if hasher.hexdigest() != expected.digest or byte_size != expected.byte_size:
                raise ValueError("evidence changed after planning")
            os.chmod(temporary_path, 0o600)
            try:
                os.link(temporary_path, destination)
                created = True
            except FileExistsError:
                created = False
        finally:
            temporary_path.unlink(missing_ok=True)
        status = self.stat(expected.digest)
        if status.verification != "verified" or status.byte_size != expected.byte_size:
            if created:
                destination.unlink(missing_ok=True)
            raise ValueError("installed evidence object failed verification")
        return EvidencePutResult(status=status, created=created)

    def put_bytes(self, data: bytes, expected: EvidenceObjectRecord) -> EvidenceStatus:
        if len(data) > MAX_EVIDENCE_INGEST_BYTES:
            raise ValueError("evidence object exceeds the local ingest limit")
        self.initialize()
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

    def read(self, digest: str, offset: int, limit: int) -> bytes:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be >= 0 and limit must be >= 1")
        path = self.object_path(digest)
        if not path.is_file():
            raise FileNotFoundError(f"evidence object is missing: {digest}")
        with path.open("rb") as stream:
            stream.seek(offset)
            return stream.read(limit)

    def copy_verified(self, digest: str, destination: Path) -> int:
        status = self.stat(digest)
        if status.verification != "verified" or status.byte_size is None:
            raise ValueError(f"evidence object is not verified: {digest}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        shutil.copyfile(self.object_path(digest), destination)
        os.chmod(destination, 0o600)
        return status.byte_size

    def retire(self, digest: str) -> bool:
        path = self.object_path(digest)
        if not path.exists():
            return False
        if not path.is_file():
            raise ValueError("evidence object path is not a regular file")
        path.unlink()
        return True

    def remove(self, digest: str) -> bool:
        return self.retire(digest)

    def stat(self, digest: str) -> EvidenceStatus:
        path = self.object_path(digest)
        if not path.is_file():
            return EvidenceStatus(
                availability="missing",
                verification="unverified",
                digest=digest,
                byte_size=None,
            )
        hasher = hashlib.sha256()
        byte_size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1_048_576):
                hasher.update(chunk)
                byte_size += len(chunk)
        actual = hasher.hexdigest()
        return EvidenceStatus(
            availability="present",
            verification="verified" if actual == digest else "corrupt",
            digest=digest,
            byte_size=byte_size,
        )

    def status(self) -> EvidenceStoreStatus:
        return EvidenceStoreStatus(
            provider="local-filesystem",
            initialized=(self.root / "objects" / "sha256").is_dir(),
        )

    def list_digests(self, limit: int) -> tuple[list[str], bool]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        object_root = self.root / "objects" / "sha256"
        if not object_root.is_dir():
            return [], False
        digests: list[str] = []
        for prefix in sorted(object_root.iterdir()):
            if not prefix.is_dir() or len(prefix.name) != 2:
                continue
            for path in sorted(prefix.iterdir()):
                digest = path.name
                if (
                    path.is_file()
                    and len(digest) == 64
                    and digest.startswith(prefix.name)
                    and all(character in "0123456789abcdef" for character in digest)
                ):
                    digests.append(digest)
                    if len(digests) > limit:
                        return digests[:limit], True
        return digests, False

    def wipe(self) -> dict[str, int]:
        if self.root.is_symlink():
            raise ValueError("evidence root must not be a symlink")
        files = [] if not self.root.is_dir() else list(self.root.rglob("*"))
        regular_files = [
            path for path in files if path.is_file() and not path.is_symlink()
        ]
        byte_size = sum(path.stat().st_size for path in regular_files)
        if self.root.exists():
            if not self.root.is_dir():
                raise ValueError("evidence root must be a directory")
            shutil.rmtree(self.root)
        self.initialize()
        return {"evidence_bytes": byte_size, "evidence_files": len(regular_files)}
