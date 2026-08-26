from __future__ import annotations

from pathlib import Path
from typing import Any

from analytical_memory.canonical import sha256_json
from analytical_memory.domain import BatchPlan
from analytical_memory.errors import IdempotencyConflictError
from analytical_memory.limits import (
    MAX_BATCH_BYTES,
    MAX_EXPLANATION_ASSERTIONS,
    MAX_QUERY_RESULTS,
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
                "validated_evidence_objects": MAX_VALIDATION_EVIDENCE_OBJECTS,
            },
            "logical_schema_fingerprint": self.schema.fingerprint,
            "operations": {
                "explain": {"enabled": True, "mutating": False},
                "ingestion_apply": {"enabled": True, "mutating": True},
                "ingestion_preview": {"enabled": True, "mutating": False},
                "query_current_facts": {"enabled": True, "mutating": False},
            },
            "record_types": list(self.schema.document["record_types"]),
            "retrieval": {
                "full_text": {"enabled": False},
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
