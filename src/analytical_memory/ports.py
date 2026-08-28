from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from analytical_memory.domain import (
    AnalyticalAttributeRequest,
    AnalyticalMetricRequest,
    EmbeddingBatch,
    EmbeddingProfileRecord,
    EmbeddingProviderInfo,
    EmbeddingRecord,
    EntityDeclaration,
    EvidenceObjectRecord,
    EvidencePutResult,
    EvidenceStatus,
    EvidenceStoreStatus,
    ImportEvidence,
    JoinRequest,
    JsonlImportRequest,
    JsonlScan,
    MemoryStoreStatus,
    NamespaceDeclaration,
    QueryPlan,
    StoredBatch,
)


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def info(self) -> EmbeddingProviderInfo:
        raise NotImplementedError

    @abstractmethod
    def embed(self, texts: list[str]) -> EmbeddingBatch:
        raise NotImplementedError


class EvidenceStore(ABC):
    @abstractmethod
    def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def put(self, source: Path, expected: EvidenceObjectRecord) -> EvidenceStatus:
        raise NotImplementedError

    @abstractmethod
    def put_tracked(
        self, source: Path, expected: EvidenceObjectRecord
    ) -> EvidencePutResult:
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
    def remove(self, digest: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> EvidenceStoreStatus:
        raise NotImplementedError

    @abstractmethod
    def list_digests(self, limit: int) -> tuple[list[str], bool]:
        raise NotImplementedError

    @abstractmethod
    def wipe(self) -> dict[str, int]:
        raise NotImplementedError


class MemoryStore(ABC):
    @abstractmethod
    def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_batch(self, idempotency_key: str) -> StoredBatch | None:
        raise NotImplementedError

    @abstractmethod
    def put_entity_declaration(
        self,
        declaration: EntityDeclaration,
        contract_fingerprint: str,
        evidence: ImportEvidence,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def put_namespace_declaration(
        self,
        declaration: NamespaceDeclaration,
        contract_fingerprint: str,
        evidence: ImportEvidence,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def import_jsonl(
        self,
        request: JsonlImportRequest,
        scan: JsonlScan,
        evidence: ImportEvidence,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def write_analytical_attribute(
        self,
        request: AnalyticalAttributeRequest,
        evidence: ImportEvidence,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def ontology_snapshot(self, namespace: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def materialize_join(
        self, request: JoinRequest, evidence: ImportEvidence
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def execute_query(self, plan: QueryPlan) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def deactivate_relation(self, relation_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete_node(self, node_id: str) -> dict[str, int]:
        raise NotImplementedError

    @abstractmethod
    def lifecycle_state(self) -> dict[str, int | str]:
        raise NotImplementedError

    @abstractmethod
    def wipe(self, expected_state: dict[str, int | str]) -> dict[str, int | str]:
        raise NotImplementedError

    @abstractmethod
    def destroy(self, expected_state: dict[str, int | str]) -> dict[str, int | str]:
        raise NotImplementedError

    @abstractmethod
    def export_current(self) -> dict[str, list[dict[str, Any]]]:
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
    def write_analytical_metric(
        self, request: AnalyticalMetricRequest, evidence: ImportEvidence
    ) -> dict[str, Any]:
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
    def release_retention(
        self, digest: str, *, released_at: str, reason: str
    ) -> dict[str, Any]:
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
    def transfer_records(self) -> dict[str, list[dict[str, Any]]]:
        raise NotImplementedError

    @abstractmethod
    def import_transfer_records(
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

    @abstractmethod
    def put_embedding_profile(self, profile: EmbeddingProfileRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_embedding_profile(self, profile_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def set_embedding_profile_status(
        self, profile_id: str, status: str, last_error: str | None
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def embedding_documents(self, profile_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def put_embedding_records(self, records: list[EmbeddingRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear_embedding_records(self, profile_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def embedding_candidates(
        self,
        profile_id: str,
        *,
        namespace: str | None,
        node_type: str | None,
        privacy_ceiling: str | None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def embedding_coverage(self, profile_id: str) -> dict[str, int]:
        raise NotImplementedError
