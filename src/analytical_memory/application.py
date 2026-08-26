from __future__ import annotations

from pathlib import Path
from typing import Any

from analytical_memory.canonical import canonical_json, sha256_json
from analytical_memory.domain import BatchPlan
from analytical_memory.errors import IdempotencyConflictError
from analytical_memory.limits import (
    MAX_BATCH_BYTES,
    MAX_EXPLANATION_ASSERTIONS,
    MAX_QUERY_RESULTS,
    MAX_SEARCH_RESULTS,
    MAX_TRAVERSAL_DEPTH,
    MAX_TRAVERSAL_RESULTS,
    MAX_VALIDATION_EVIDENCE_OBJECTS,
)
from analytical_memory.planner import plan_batch
from analytical_memory.ports import EvidenceStore, MemoryStore
from analytical_memory.schema_contract import SchemaContract


class MemoryApplication:
    def __init__(
        self,
        memory_store: MemoryStore,
        evidence_store: EvidenceStore,
        schema: SchemaContract,
    ) -> None:
        self.memory_store = memory_store
        self.evidence_store = evidence_store
        self.schema = schema

    def initialize(self) -> dict[str, Any]:
        self.memory_store.initialize()
        self.evidence_store.initialize()
        return {
            "initialized": True,
            "schema_fingerprint": self.schema.fingerprint,
        }

    def plan(self, batch_path: Path) -> BatchPlan:
        return plan_batch(batch_path, self.schema)

    def preview(self, batch_path: Path) -> dict[str, Any]:
        return self.plan(batch_path).preview()

    def apply(self, batch_path: Path) -> dict[str, Any]:
        plan = self.plan(batch_path)
        existing = self.memory_store.get_batch(plan.idempotency_key)
        if existing is not None:
            if existing.input_hash != plan.input_hash:
                raise IdempotencyConflictError(
                    "idempotency key already exists with different input"
                )
            return {"replayed": True, "result": existing.result}

        self.evidence_store.put(plan.evidence.source_path, plan.evidence.object)
        result = self.memory_store.apply(plan)
        return {"replayed": False, "result": result}

    def current_facts(self) -> dict[str, Any]:
        return {
            "query": "current-facts",
            "results": self.memory_store.current_facts(),
            "schema_fingerprint": self.schema.fingerprint,
        }

    def current_slots(self) -> dict[str, Any]:
        return {
            "query": "current-slots",
            "results": self.memory_store.current_slots(),
            "schema_fingerprint": self.schema.fingerprint,
        }

    def current_metric(
        self, definition_version: str, dimensions: dict[str, Any]
    ) -> dict[str, Any]:
        dimensions_json = canonical_json(dimensions)
        metric = self.memory_store.current_metric(definition_version, dimensions_json)
        return {
            "query": "current-metric",
            "definition_version": definition_version,
            "dimensions": dimensions,
            "metric": metric,
            "coverage": {
                "complete": metric is not None,
                "selected_count": 0 if metric is None else 1,
            },
            "schema_fingerprint": self.schema.fingerprint,
        }

    def traverse_relations(
        self,
        start_node_id: str,
        *,
        relation_types: list[str] | None = None,
        direction: str = "outbound",
        max_depth: int = 3,
        limit: int = 100,
        states: list[str] | None = None,
    ) -> dict[str, Any]:
        if direction not in {"outbound", "inbound", "both"}:
            raise ValueError("direction must be outbound, inbound, or both")
        if not 1 <= max_depth <= MAX_TRAVERSAL_DEPTH:
            raise ValueError(f"max_depth must be between 1 and {MAX_TRAVERSAL_DEPTH}")
        if not 1 <= limit <= MAX_TRAVERSAL_RESULTS:
            raise ValueError(f"limit must be between 1 and {MAX_TRAVERSAL_RESULTS}")
        allowed_states = set(states or ["supported", "contested"])
        unknown_states = allowed_states - {
            "supported",
            "contested",
            "contradicted",
            "unasserted",
        }
        if unknown_states:
            raise ValueError(f"unknown relation states: {sorted(unknown_states)}")
        result = self.memory_store.traverse_relations(
            start_node_id,
            relation_types=relation_types,
            direction=direction,
            max_depth=max_depth,
            limit=limit,
            states=sorted(allowed_states),
        )
        result["schema_fingerprint"] = self.schema.fingerprint
        return result

    def search_text(self, query: str, limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise ValueError(f"limit must be between 1 and {MAX_SEARCH_RESULTS}")
        result = self.memory_store.search_text(query, limit)
        enriched: list[dict[str, Any]] = []
        for match in result["results"]:
            explanation = self.explain(str(match["target_id"]))
            enriched.append(
                {
                    **match,
                    "fact": explanation["fact"],
                    "provenance": {
                        "assertions": explanation["assertions"],
                        "node": explanation["node"],
                    },
                }
            )
        return {
            "query": "search-text",
            "text": query,
            "results": enriched,
            "coverage": result["coverage"],
            "schema_fingerprint": self.schema.fingerprint,
        }

    def explain(self, attribute_id: str) -> dict[str, Any]:
        explanation = self.memory_store.explain_attribute(attribute_id)
        for assertion in explanation["assertions"]:
            for binding in assertion["evidence"]:
                digest = str(binding["object"]["digest"])
                status = self.evidence_store.stat(digest)
                binding["status"] = {
                    "availability": status.availability,
                    "verification": status.verification,
                    "byte_size": status.byte_size,
                }
        explanation["schema_fingerprint"] = self.schema.fingerprint
        return explanation

    def explain_relation(self, relation_id: str) -> dict[str, Any]:
        explanation = self.memory_store.explain_relation(relation_id)
        for assertion in explanation["assertions"]:
            self._add_evidence_status(assertion["evidence"])
        explanation["schema_fingerprint"] = self.schema.fingerprint
        return explanation

    def explain_metric(self, metric_id: str) -> dict[str, Any]:
        explanation = self.memory_store.explain_metric(metric_id)
        self._add_evidence_status(explanation["evidence"])
        explanation["schema_fingerprint"] = self.schema.fingerprint
        return explanation

    def _add_evidence_status(self, bindings: list[dict[str, Any]]) -> None:
        for binding in bindings:
            digest = str(binding["object"]["digest"])
            status = self.evidence_store.stat(digest)
            binding["status"] = {
                "availability": status.availability,
                "verification": status.verification,
                "byte_size": status.byte_size,
            }

    def capabilities(self) -> dict[str, Any]:
        memory_status = self.memory_store.status()
        evidence_status = self.evidence_store.status()
        document: dict[str, Any] = {
            "capabilities_document_version": "1",
            "evidence_store": {
                "initialized": evidence_status.initialized,
                "provider": evidence_status.provider,
                "raw_read": {"enabled": False, "max_bytes": 0},
            },
            "limits": {
                "ingestion_batch_bytes": MAX_BATCH_BYTES,
                "returned_explanation_assertions": MAX_EXPLANATION_ASSERTIONS,
                "returned_query_items": MAX_QUERY_RESULTS,
                "search_results": MAX_SEARCH_RESULTS,
                "traversal_depth": MAX_TRAVERSAL_DEPTH,
                "traversal_results": MAX_TRAVERSAL_RESULTS,
                "validated_evidence_objects": MAX_VALIDATION_EVIDENCE_OBJECTS,
            },
            "logical_schema_fingerprint": self.schema.fingerprint,
            "operations": {
                "explain": {"enabled": True, "mutating": False},
                "ingestion_apply": {"enabled": True, "mutating": True},
                "ingestion_preview": {"enabled": True, "mutating": False},
                "query_current_facts": {"enabled": True, "mutating": False},
                "query_current_metric": {"enabled": True, "mutating": False},
                "query_current_slots": {"enabled": True, "mutating": False},
                "search_text": {"enabled": True, "mutating": False},
                "traverse_relations": {"enabled": True, "mutating": False},
            },
            "record_types": list(self.schema.document["record_types"]),
            "retrieval": {
                "full_text": {"enabled": True, "engine": "sqlite-fts5"},
                "vector": {"enabled": False, "mode": "disabled"},
            },
            "saved_queries": sorted(self.schema.document["saved_queries"]),
            "storage": {
                "backend": memory_status.backend,
                "initialized": memory_status.initialized,
                "migration_version": memory_status.schema_version,
            },
            "transports": {
                "cli": {"enabled": True},
                "python": {"enabled": True},
                "stdio_mcp": {"enabled": True},
            },
        }
        document["runtime_fingerprint"] = sha256_json(document)
        return document

    def status(self) -> dict[str, Any]:
        capabilities = self.capabilities()
        storage = capabilities["storage"]
        evidence_store = capabilities["evidence_store"]
        return {
            "ready": bool(storage["initialized"] and evidence_store["initialized"]),
            "runtime_fingerprint": capabilities["runtime_fingerprint"],
            "schema_fingerprint": self.schema.fingerprint,
            "storage": storage,
            "evidence_store": evidence_store,
        }

    def validate(self) -> dict[str, Any]:
        memory_status = self.memory_store.status()
        evidence_status = self.evidence_store.status()
        issues: list[str] = []
        if not memory_status.initialized:
            issues.append("memory store is not initialized")
        if not evidence_status.initialized:
            issues.append("evidence store is not initialized")

        integrity: dict[str, Any] | None = None
        evidence_checks: list[dict[str, Any]] = []
        evidence_complete = True
        if memory_status.initialized:
            integrity = self.memory_store.integrity()
            if not integrity["ok"]:
                issues.append("memory store integrity check failed")
            digests, truncated = self.memory_store.evidence_digests(
                MAX_VALIDATION_EVIDENCE_OBJECTS
            )
            evidence_complete = not truncated
            if truncated:
                issues.append("evidence validation limit reached")
            for digest in digests:
                check = self.evidence_store.stat(digest)
                evidence_checks.append(
                    {
                        "availability": check.availability,
                        "byte_size": check.byte_size,
                        "digest": digest,
                        "verification": check.verification,
                    }
                )
                if check.verification != "verified":
                    issues.append(f"evidence object is not verified: {digest}")

        return {
            "capabilities": self.capabilities(),
            "evidence": {
                "checks": evidence_checks,
                "complete": evidence_complete,
            },
            "integrity": integrity,
            "issues": issues,
            "ok": not issues,
            "schema": {
                "fingerprint": self.schema.fingerprint,
                "valid": True,
            },
        }
