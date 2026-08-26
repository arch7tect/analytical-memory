from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from analytical_memory.domain import (
    BatchPlan,
    EvidenceObjectRecord,
    EvidenceStatus,
    StoredBatch,
)


class EvidenceStore(ABC):
    @abstractmethod
    def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def put(self, source: Path, expected: EvidenceObjectRecord) -> EvidenceStatus:
        raise NotImplementedError

    @abstractmethod
    def stat(self, digest: str) -> EvidenceStatus:
        raise NotImplementedError


class MemoryStore(ABC):
    @abstractmethod
    def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_batch(self, idempotency_key: str) -> StoredBatch | None:
        raise NotImplementedError

    @abstractmethod
    def apply(self, plan: BatchPlan) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def current_facts(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def explain_attribute(self, attribute_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def integrity(self) -> dict[str, Any]:
        raise NotImplementedError
