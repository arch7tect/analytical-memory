from __future__ import annotations

from pathlib import Path
from typing import Any

from analytical_memory.api_models import (
    AnalyticalAttributeResponse,
    AnalyticalMetricResponse,
    CurrentMetricResponse,
    DirectRelationExplanation,
    EmbeddingProfileResponse,
    EvidenceAuditResponse,
    EvidenceReadResponse,
    EvidenceStatusResponse,
    EvidenceVerifyResponse,
    ExplanationResponse,
    JoinMaterializationResponse,
    JsonlImportResponse,
    MetricExplanationResponse,
    NodeDeleteResponse,
    OntologyResponse,
    QueryIRResponse,
    RelationExplanationResponse,
    SearchResponse,
    SemanticSearchResponse,
    TraversalResponse,
)
from analytical_memory.application import MemoryApplication


class MemoryAPI:
    def __init__(self, application: MemoryApplication) -> None:
        self.application = application

    def declare_entity(
        self,
        entity_type: str,
        privacy: str,
        fields: dict[str, dict[str, Any]],
        contract_fingerprint: str,
    ) -> OntologyResponse:
        return OntologyResponse.model_validate(
            self.application.declare_entity(
                entity_type,
                privacy=privacy,
                fields=fields,
                contract_fingerprint=contract_fingerprint,
            )
        )

    def ontology(self, namespace: str | None = None) -> OntologyResponse:
        return OntologyResponse.model_validate(self.application.ontology(namespace))

    def jsonl_import(
        self,
        source_path: str | Path,
        entity_type: str,
        key: list[dict[str, str]],
        contract_fingerprint: str,
    ) -> JsonlImportResponse:
        return JsonlImportResponse.model_validate(
            self.application.jsonl_import(
                source_path,
                entity_type=entity_type,
                key=key,
                contract_fingerprint=contract_fingerprint,
            )
        )

    def materialize_join(
        self,
        name: str,
        relation: str,
        from_: dict[str, Any],
        to: dict[str, Any],
        contract_fingerprint: str,
        idempotency_key: str | None = None,
    ) -> JoinMaterializationResponse:
        return JoinMaterializationResponse.model_validate(
            self.application.materialize_join(
                name=name,
                relation=relation,
                from_=from_,
                to=to,
                contract_fingerprint=contract_fingerprint,
                idempotency_key=idempotency_key,
            )
        )

    def write_analytical_attribute(
        self,
        node_id: str,
        attribute_name: str,
        value: Any,
        method: str,
        contract_fingerprint: str,
    ) -> AnalyticalAttributeResponse:
        return AnalyticalAttributeResponse.model_validate(
            self.application.write_analytical_attribute(
                node_id,
                attribute_name,
                value,
                method=method,
                contract_fingerprint=contract_fingerprint,
            )
        )

    def execute_query(self, document: dict[str, Any]) -> QueryIRResponse:
        return QueryIRResponse.model_validate(self.application.execute_query(document))

    def write_analytical_metric(
        self,
        definition_version: str,
        value: Any,
        dimensions: dict[str, Any],
        method: str,
        method_version: str,
        contract_fingerprint: str,
        coverage: dict[str, Any] | None = None,
        complete: bool = True,
        unit: str | None = None,
        numerator: float | None = None,
        denominator: float | None = None,
        privacy: str = "public",
    ) -> AnalyticalMetricResponse:
        return AnalyticalMetricResponse.model_validate(
            self.application.write_analytical_metric(
                definition_version,
                value,
                dimensions,
                method=method,
                method_version=method_version,
                contract_fingerprint=contract_fingerprint,
                coverage=coverage,
                complete=complete,
                unit=unit,
                numerator=numerator,
                denominator=denominator,
                privacy=privacy,
            )
        )

    def deactivate_relation(self, relation_id: str) -> DirectRelationExplanation:
        return DirectRelationExplanation.model_validate(
            self.application.deactivate_relation(relation_id)
        )

    def delete_node(self, node_id: str) -> NodeDeleteResponse:
        return NodeDeleteResponse.model_validate(self.application.delete_node(node_id))

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

    def embedding_profile_create(
        self, attribute_name: str, privacy_ceiling: str | None = None
    ) -> EmbeddingProfileResponse:
        return EmbeddingProfileResponse.model_validate(
            self.application.embedding_profile_create(
                attribute_name, privacy_ceiling=privacy_ceiling
            )
        )

    def embedding_profile_status(self, profile_id: str) -> EmbeddingProfileResponse:
        return EmbeddingProfileResponse.model_validate(
            self.application.embedding_profile_status(profile_id)
        )

    def embedding_rebuild(
        self, profile_id: str, *, reset: bool = False
    ) -> EmbeddingProfileResponse:
        return EmbeddingProfileResponse.model_validate(
            self.application.embedding_rebuild(profile_id, reset=reset)
        )

    def search_semantic(
        self,
        profile_id: str,
        query: str,
        *,
        namespace: str | None = None,
        node_type: str | None = None,
        privacy_ceiling: str | None = None,
        limit: int = 20,
    ) -> SemanticSearchResponse:
        return SemanticSearchResponse.model_validate(
            self.application.search_semantic(
                profile_id,
                query,
                namespace=namespace,
                node_type=node_type,
                privacy_ceiling=privacy_ceiling,
                limit=limit,
            )
        )

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
