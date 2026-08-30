from __future__ import annotations

from typing import Any

_OUTPUT_FIELD_DESCRIPTIONS = {
    "active": "Whether the current relation is active.",
    "active_edges": "Number of active relation edges in this scope.",
    "active_relations": "Total number of active relations in the ontology scope.",
    "attribute": "Explained current attribute and its direct provenance fields.",
    "attribute_id": "Canonical identifier of the current attribute.",
    "attribute_name": "Attribute name within its entity type.",
    "attributes": "Number of current attributes affected by the operation.",
    "attributes_written": "Number of fields written from accepted import records.",
    "availability": "Whether the referenced evidence bytes are present or missing.",
    "batch_id": "Canonical identifier of the ingestion or mutation batch.",
    "bindings": "Mapping from query aliases to canonical Node IDs.",
    "byte_count": "Number of evidence bytes returned in this chunk.",
    "byte_size": "Total size of the evidence object in bytes, when known.",
    "checked_at": "UTC timestamp when evidence verification was performed.",
    "complete": "Whether the result covers the full requested scope.",
    "configured": "Whether the external provider is configured.",
    "content": "Normalized text represented by the search document.",
    "content_hash": "SHA-256 hash of normalized searchable content.",
    "contract_fingerprint": (
        "Structural write gate whose value equals schema_fingerprint from "
        "memory://schema/current."
    ),
    "contract_hash": "Hash of the immutable embedding-profile contract.",
    "count": "Aggregate row count for a count query; absent for row queries.",
    "coverage": "Completeness or population details for the containing result.",
    "created_at": "UTC timestamp when the record was created.",
    "created_nodes": "Number of new Nodes created by the import.",
    "created_relations": "Number of new active relation edges materialized.",
    "data_base64": "Requested evidence bytes encoded as base64.",
    "declaration_created": "Whether this operation created the relation declaration.",
    "declared": "Whether this ontology item was explicitly declared by a user.",
    "definition_hash": "Canonical hash of the join definition.",
    "definition_version": "Version of the analytical metric definition.",
    "denominator": "Optional denominator used to calculate a metric value.",
    "depth": "Shortest traversal depth from the start Node.",
    "description": "Human-readable ontology description, when declared.",
    "digest": "Lowercase SHA-256 digest identifying an evidence object.",
    "dimensions": "Exact dimension object defining a metric observation scope.",
    "direction": "Direction applied by traversal or ordering.",
    "display_label": "Best available human-readable label for a Node.",
    "document": "Complete current ontology document after the mutation.",
    "document_id": "Canonical identifier of the indexed search document.",
    "edges": "Relation edges returned by the traversal.",
    "effective_privacy": "Effective privacy class after provenance inheritance.",
    "eligible_count": "Number of current facts eligible for this index or profile.",
    "embeddings": "Number of current embeddings affected by the operation.",
    "enabled": "Whether this relation declaration may be materialized.",
    "entities": "Current entity-type definitions in the ontology.",
    "eof": "Whether this chunk reaches the end of the evidence object.",
    "evidence": "Direct evidence summary for the explained record.",
    "evidence_availability": "Evidence availability recorded for the operation.",
    "evidence_digest": "SHA-256 digest of the operation's raw evidence object.",
    "evidence_verification": "Verification state recorded for the evidence object.",
    "expected_digest": "Evidence digest expected from the stored fragment.",
    "field": "Field expression or attribute name used by this result item.",
    "fields": "Field definitions belonging to an ontology entity.",
    "fragment_id": "Canonical provenance fragment identifier.",
    "fragments": "Per-fragment evidence verification results.",
    "from": "Declared source entity type for the directed relation.",
    "id": "Canonical identifier of the containing object.",
    "idempotency_key": (
        "Stable key identifying the logical write operation; its source is "
        "operation-specific."
    ),
    "inactive_edges": "Number of inactive relation edges in this scope.",
    "indexed_count": "Number of eligible current facts present in the index.",
    "invalidated": "Whether this immutable metric observation was invalidated.",
    "json_type": "Canonical JSON value type used for typed comparison.",
    "kind": "Source or target category for the containing record.",
    "last_error": "Latest embedding-profile error, if one was recorded.",
    "limit": "Maximum evidence bytes requested for this chunk.",
    "locator": "Original non-secret source locator recorded for provenance.",
    "logical_key": "Stable logical key identifying a relation across corrections.",
    "matches": "Whether provider configuration matches the stored profile.",
    "max_depth": "Maximum traversal depth applied to the query.",
    "media_type": "Recorded media type of the evidence object.",
    "method": "Method name recorded for the analytical run.",
    "method_version": "Version of the method that produced the metric.",
    "metric": "Selected immutable metric observation, if one matches exactly.",
    "metric_id": "Canonical identifier of an immutable metric observation.",
    "model": "Embedding model recorded by the profile.",
    "name": "Stable name of the containing declaration or definition.",
    "namespace": "Ontology namespace containing the entity type.",
    "namespaces": "Current namespace definitions in the ontology.",
    "node": "Node directly owning the explained attribute.",
    "node_id": "Canonical identifier of the Node owning this value.",
    "node_type": "Namespaced entity type of the matched Node.",
    "nodes": "Nodes returned or affected by the operation.",
    "nullable": "Whether a declared field may contain JSON null.",
    "numerator": "Optional numerator used to calculate a metric value.",
    "offset": "Zero-based byte offset of this evidence chunk.",
    "ontology_delta": "New ontology shape observed during the import.",
    "ontology_fingerprint": "Fingerprint of the selected memory's current ontology.",
    "ontology_version": "Version of the ontology document format.",
    "ordering": "Effective deterministic ordering applied to query rows.",
    "orphans": "Evidence files that are not referenced by current metadata.",
    "outcome": "Result of reproducing and comparing one fragment digest.",
    "preprocessing_version": "Version of text preprocessing used for embeddings.",
    "previously_materialized_active": "Matching active edges that already existed.",
    "previously_materialized_inactive": "Matching inactive edges left unchanged.",
    "privacy": "Declared export and external-processing privacy class.",
    "privacy_ceiling": "Highest privacy class accepted by the embedding profile.",
    "privacy_class": "Effective privacy class of this current record.",
    "profile": "Stored embedding profile definition.",
    "profile_id": "Canonical identifier of the embedding profile used for search.",
    "projections": "Requested projected values with direct provenance.",
    "provenance": "Direct provenance records for this ontology item.",
    "provider": "Embedding provider recorded by the profile.",
    "query": "Normalized query criteria echoed by the server.",
    "rank": "Text-search rank, where a smaller value is a better match.",
    "record_id": "Canonical identifier of the source record for this value.",
    "recorded_at": "UTC timestamp when the observation or provenance was recorded.",
    "records": "Number of accepted JSONL records in the import.",
    "relation": "Explained relation or declared relation name.",
    "relation_id": "Canonical identifier of a relation edge.",
    "relation_type": "Namespaced type of the directed relation.",
    "relations": "Current relation definitions or affected edges for this result.",
    "replayed": "Whether an earlier committed idempotent operation was returned.",
    "reproduced_digest": "Digest reproduced from current evidence bytes.",
    "required": "Whether a declared field must be present on imported records.",
    "results": "Ordered result items returned by the operation.",
    "retired": "Whether the evidence object is marked retired.",
    "rows": "Ordered Query IR rows; absent for count queries.",
    "run": "Analytical run that produced the explained observation.",
    "run_id": "Canonical identifier of the provenance or analytical run.",
    "run_method": "Method name recorded on the selected metric's run.",
    "schema_fingerprint": "Structural schema fingerprint used to produce the result.",
    "score": "Exact similarity score, where a larger value is a better match.",
    "search_documents": "Number of current search documents affected.",
    "searchable": "Whether the field participates in public text search.",
    "selected_count": "Number of metric observations selected after exact filtering.",
    "similarity": "Similarity function fixed by the embedding profile.",
    "skipped_null_or_missing": "Source Nodes skipped for null or absent join fields.",
    "skipped_unmatched": "Source Nodes skipped because no target tuple matched.",
    "source": "Direct source summary or source-side Node for this result.",
    "source_id": "Canonical identifier of the provenance source.",
    "source_node_id": "Canonical identifier of the relation's source Node.",
    "start_node_id": "Canonical Node ID from which traversal started.",
    "states": "Relation activity states included in traversal.",
    "statistics": "Current counts for the containing ontology scope.",
    "status": "Current lifecycle or readiness state of the containing object.",
    "target": "Target-side Node for a relation or traversal edge.",
    "target_id": "Canonical identifier of the matched search target.",
    "target_kind": "Kind of record addressed by the search result.",
    "target_node_id": "Canonical identifier of the relation's target Node.",
    "text": "Original search text echoed by the server.",
    "tie_breaker": "Deterministic secondary ordering used for equal values.",
    "to": "Declared target entity type for the directed relation.",
    "truncated": "Whether a configured result bound omitted additional items.",
    "type": "Namespaced entity type or canonical value type in this object.",
    "unit": "Optional unit associated with the metric value.",
    "updated_at": "UTC timestamp of the current record version.",
    "updated_nodes": "Number of existing Nodes patched by the import.",
    "value": "Canonical JSON value carried by this result item.",
    "verification": "Current evidence verification state.",
}


def describe_known_response_properties(
    schema: dict[str, Any], _model: type[Any]
) -> None:
    for name, field_schema in schema.get("properties", {}).items():
        description = _OUTPUT_FIELD_DESCRIPTIONS.get(name)
        if description is not None:
            field_schema.setdefault("description", description)


def describe_response_schema(schema: dict[str, Any]) -> dict[str, Any]:
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for name, field_schema in value.get("properties", {}).items():
                if "description" not in field_schema:
                    try:
                        field_schema["description"] = _OUTPUT_FIELD_DESCRIPTIONS[name]
                    except KeyError as exc:
                        raise ValueError(
                            f"missing MCP output description for field {name!r}"
                        ) from exc
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return schema


class DescribedMCPResponse:
    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> Any:
        return describe_response_schema(handler(core_schema))
