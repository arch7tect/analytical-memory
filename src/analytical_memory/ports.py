from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from analytical_memory.domain import (
    BatchPlan,
    EvidenceObjectRecord,
    EvidenceStatus,
    EvidenceStoreStatus,
    MemoryStoreStatus,
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
    def put_bytes(self, data: bytes, expected: EvidenceObjectRecord) -> EvidenceStatus:
        raise NotImplementedError

    @abstractmethod
    def stat(self, digest: str) -> EvidenceStatus:
        raise NotImplementedError

    @abstractmethod
    def read(self, digest: str, offset: int, limit: int) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def copy_verified(self, digest: str, destination: Path) -> int:
        raise NotImplementedError

    @abstractmethod
    def retire(self, digest: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> EvidenceStoreStatus:
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
    def current_slots(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def current_relations(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def traverse_relations(
        self,
        start_node_id: str,
        *,
        relation_types: list[str] | None,
        direction: str,
        max_depth: int,
        limit: int,
        states: list[str],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_node(self, node_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def current_metric(
        self, definition_version: str, dimensions_json: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def search_text(self, query: str, limit: int) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def explain_attribute(self, attribute_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def explain_relation(self, relation_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def explain_metric(self, metric_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def evidence_catalog(
        self, limit: int, digest: str | None = None
    ) -> tuple[list[dict[str, Any]], bool]:
        raise NotImplementedError

    @abstractmethod
    def record_evidence_check(
        self,
        digest: str,
        *,
        availability: str,
        verification: str,
        byte_size: int | None,
        checked_at: str,
        method: str,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def record_fragment_check(
        self,
        fragment_id: str,
        *,
        digest: str,
        outcome: str,
        byte_size: int | None,
        checked_at: str,
        method: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_artifact_check(
        self,
        target_kind: str,
        target_id: str,
        *,
        digest: str,
        outcome: str,
        byte_size: int | None,
        checked_at: str,
        method: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def retention_report(self, as_of: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def record_retirement(
        self, digest: str, *, plan_id: str, reason: str, retired_at: str
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_retirements(
        self,
        digests: list[str],
        *,
        plan_id: str,
        reason: str,
        retired_at: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def snapshot_records(self) -> dict[str, list[dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def import_snapshot_records(
        self, records: dict[str, list[dict[str, Any]]]
    ) -> dict[str, int]:
        raise NotImplementedError

    @abstractmethod
    def integrity(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> MemoryStoreStatus:
        raise NotImplementedError

    @abstractmethod
    def evidence_digests(self, limit: int) -> tuple[list[str], bool]:
        raise NotImplementedError
