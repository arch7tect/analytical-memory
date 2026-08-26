from __future__ import annotations

from pathlib import Path

from analytical_memory.api_models import (
    ApplyResponse,
    CurrentFactsResponse,
    CurrentMetricResponse,
    CurrentSlotsResponse,
    EvidenceAuditResponse,
    EvidenceReadResponse,
    EvidenceStatusResponse,
    EvidenceVerifyResponse,
    ExplanationResponse,
    MetricExplanationResponse,
    PreviewResponse,
    RelationExplanationResponse,
    SearchResponse,
    TraversalResponse,
)
from analytical_memory.application import MemoryApplication


class MemoryAPI:
    def __init__(self, application: MemoryApplication) -> None:
        self.application = application

    def ingestion_preview(self, batch_path: str | Path) -> PreviewResponse:
        return PreviewResponse.model_validate(
            self.application.preview(Path(batch_path))
        )

    def ingestion_apply(self, batch_path: str | Path) -> ApplyResponse:
        return ApplyResponse.model_validate(self.application.apply(Path(batch_path)))

    def query_current_facts(self) -> CurrentFactsResponse:
        return CurrentFactsResponse.model_validate(self.application.current_facts())

    def query_current_slots(self) -> CurrentSlotsResponse:
        return CurrentSlotsResponse.model_validate(self.application.current_slots())

    def query_current_metric(
        self, definition_version: str, dimensions: dict[str, object]
    ) -> CurrentMetricResponse:
        return CurrentMetricResponse.model_validate(
            self.application.current_metric(definition_version, dimensions)
        )

    def traverse_relations(
        self,
        start_node_id: str,
        *,
        relation_types: list[str] | None = None,
        direction: str = "outbound",
        max_depth: int = 3,
        limit: int = 100,
        states: list[str] | None = None,
    ) -> TraversalResponse:
        return TraversalResponse.model_validate(
            self.application.traverse_relations(
                start_node_id,
                relation_types=relation_types,
                direction=direction,
                max_depth=max_depth,
                limit=limit,
                states=states,
            )
        )

    def search_text(self, query: str, limit: int = 20) -> SearchResponse:
        return SearchResponse.model_validate(self.application.search_text(query, limit))

    def explain(self, attribute_id: str) -> ExplanationResponse:
        return ExplanationResponse.model_validate(
            self.application.explain(attribute_id)
        )

    def explain_relation(self, relation_id: str) -> RelationExplanationResponse:
        return RelationExplanationResponse.model_validate(
            self.application.explain_relation(relation_id)
        )

    def explain_metric(self, metric_id: str) -> MetricExplanationResponse:
        return MetricExplanationResponse.model_validate(
            self.application.explain_metric(metric_id)
        )

    def evidence_status(self, digest: str) -> EvidenceStatusResponse:
        return EvidenceStatusResponse.model_validate(
            self.application.evidence_status(digest)
        )

    def evidence_read(
        self, digest: str, *, offset: int = 0, limit: int = 65536
    ) -> EvidenceReadResponse:
        return EvidenceReadResponse.model_validate(
            self.application.evidence_read(digest, offset=offset, limit=limit)
        )

    def evidence_verify(self, digest: str) -> EvidenceVerifyResponse:
        return EvidenceVerifyResponse.model_validate(
            self.application.evidence_verify(digest)
        )

    def evidence_audit(self, limit: int = 1000) -> EvidenceAuditResponse:
        return EvidenceAuditResponse.model_validate(
            self.application.evidence_audit(limit=limit)
        )
