from __future__ import annotations

from pathlib import Path
from typing import Any

from analytical_memory.domain import BatchPlan
from analytical_memory.errors import IdempotencyConflictError
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
