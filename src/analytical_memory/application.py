from __future__ import annotations

import base64
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from analytical_memory.canonical import (
    canonical_json,
    sha256_bytes,
    sha256_json,
    stable_uuid,
)
from analytical_memory.domain import (
    BatchPlan,
    EmbeddingProfileRecord,
    EmbeddingRecord,
)
from analytical_memory.errors import (
    EmbeddingProviderError,
    IdempotencyConflictError,
    RecordNotFoundError,
    RetentionBlockedError,
)
from analytical_memory.evidence import PRIVACY_ORDER, select_fragment
from analytical_memory.limits import (
    MAX_BATCH_BYTES,
    MAX_EVIDENCE_AUDIT_OBJECTS,
    MAX_EVIDENCE_READ_BYTES,
    MAX_EVIDENCE_VERIFY_BYTES,
    MAX_EXPLANATION_ASSERTIONS,
    MAX_QUERY_RESULTS,
    MAX_SEARCH_RESULTS,
    MAX_SNAPSHOT_BYTES,
    MAX_TRAVERSAL_DEPTH,
    MAX_TRAVERSAL_RESULTS,
    MAX_VALIDATION_EVIDENCE_OBJECTS,
)
from analytical_memory.planner import plan_batch
from analytical_memory.ports import EmbeddingProvider, EvidenceStore, MemoryStore
from analytical_memory.schema_contract import SchemaContract
from analytical_memory.snapshot import create_snapshot, import_snapshot, load_snapshot
from analytical_memory.vectors import (
    cosine_similarity,
    decode_vector,
    encode_vector,
    preprocess_text,
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class MemoryApplication:
    def __init__(
        self,
        memory_store: MemoryStore,
        evidence_store: EvidenceStore,
        schema: SchemaContract,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.evidence_store = evidence_store
        self.schema = schema
        self.embedding_provider = embedding_provider

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
        for evidence_object, data in plan.evidence.materialized_objects:
            self.evidence_store.put_bytes(data, evidence_object)
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

    def embedding_profile_create(
        self,
        attribute_name: str,
        *,
        privacy_ceiling: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        provider = self._require_embedding_provider()
        info = provider.info
        ceiling = privacy_ceiling or info.privacy_ceiling
        if ceiling not in PRIVACY_ORDER:
            raise ValueError("unknown privacy ceiling")
        if PRIVACY_ORDER[ceiling] > PRIVACY_ORDER[info.privacy_ceiling]:
            raise ValueError("profile privacy ceiling exceeds provider policy")
        attribute_name = attribute_name.strip()
        if not attribute_name:
            raise ValueError("attribute_name must not be empty")
        contract = {
            "attribute_name": attribute_name,
            "dimensions": info.dimensions,
            "model": info.model,
            "preprocessing_version": info.preprocessing_version,
            "privacy_ceiling": ceiling,
            "provider": info.provider,
            "similarity": "cosine",
        }
        contract_hash = sha256_json(contract)
        profile = EmbeddingProfileRecord(
            id=stable_uuid("embedding-profile", contract_hash),
            attribute_name=attribute_name,
            provider=info.provider,
            model=info.model,
            dimensions=info.dimensions,
            preprocessing_version=info.preprocessing_version,
            similarity="cosine",
            privacy_ceiling=ceiling,
            contract_hash=contract_hash,
            status="pending",
            last_error=None,
            created_at=created_at or _now(),
        )
        self.memory_store.put_embedding_profile(profile)
        return self.embedding_profile_status(profile.id)

    def embedding_profile_status(self, profile_id: str) -> dict[str, Any]:
        profile = self.memory_store.get_embedding_profile(profile_id)
        coverage = self.memory_store.embedding_coverage(profile_id)
        provider_matches = self._provider_matches_profile(profile)
        configured = bool(
            self.embedding_provider is not None
            and self.embedding_provider.info.configured
        )
        coverage_complete = coverage["eligible_count"] == coverage["indexed_count"]
        if profile["status"] == "ready" and (
            not provider_matches or not configured or not coverage_complete
        ):
            profile = {**profile, "status": "degraded"}
        return {
            "profile": profile,
            "coverage": {
                **coverage,
                "complete": coverage_complete,
            },
            "provider": {
                "configured": configured,
                "matches": provider_matches,
            },
            "schema_fingerprint": self.schema.fingerprint,
        }

    def embedding_rebuild(
        self, profile_id: str, *, reset: bool = False
    ) -> dict[str, Any]:
        profile = self.memory_store.get_embedding_profile(profile_id)
        try:
            provider = self._require_matching_provider(profile)
        except EmbeddingProviderError as exc:
            self.memory_store.set_embedding_profile_status(
                profile_id, "degraded", str(exc)
            )
            return self.embedding_profile_status(profile_id)
        if not provider.info.configured:
            self.memory_store.set_embedding_profile_status(
                profile_id, "degraded", "embedding provider is not configured"
            )
            return self.embedding_profile_status(profile_id)
        if reset:
            self.memory_store.clear_embedding_records(profile_id)
        documents = self.memory_store.embedding_documents(profile_id)
        self.memory_store.set_embedding_profile_status(profile_id, "building", None)
        try:
            records: list[EmbeddingRecord] = []
            for start in range(0, len(documents), 64):
                group = documents[start : start + 64]
                texts = [preprocess_text(str(item["content"])) for item in group]
                batch = provider.embed(texts)
                if batch.response_model != str(profile["model"]):
                    raise EmbeddingProviderError(
                        "embedding API response model does not match the profile"
                    )
                for document, vector in zip(group, batch.vectors, strict=True):
                    records.append(
                        EmbeddingRecord(
                            id=stable_uuid(
                                "embedding-record",
                                document["id"],
                                profile_id,
                                document["content_hash"],
                            ),
                            search_document_id=str(document["id"]),
                            profile_id=profile_id,
                            input_content_hash=str(document["content_hash"]),
                            vector_blob=encode_vector(
                                vector, int(profile["dimensions"])
                            ),
                            dimensions=int(profile["dimensions"]),
                            response_model=batch.response_model,
                            created_at=_now(),
                        )
                    )
            self.memory_store.put_embedding_records(records)
            coverage = self.memory_store.embedding_coverage(profile_id)
            status = (
                "ready"
                if coverage["eligible_count"] == coverage["indexed_count"]
                else "degraded"
            )
            self.memory_store.set_embedding_profile_status(profile_id, status, None)
        except (EmbeddingProviderError, ValueError) as exc:
            self.memory_store.set_embedding_profile_status(
                profile_id, "degraded", str(exc)
            )
        return self.embedding_profile_status(profile_id)

    def search_semantic(
        self,
        profile_id: str,
        query: str,
        *,
        namespace: str | None = None,
        node_type: str | None = None,
        privacy_ceiling: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise ValueError(f"limit must be between 1 and {MAX_SEARCH_RESULTS}")
        profile = self.memory_store.get_embedding_profile(profile_id)
        effective_ceiling = privacy_ceiling or str(profile["privacy_ceiling"])
        if effective_ceiling not in PRIVACY_ORDER:
            raise ValueError("unknown privacy ceiling")
        if (
            PRIVACY_ORDER[effective_ceiling]
            > PRIVACY_ORDER[str(profile["privacy_ceiling"])]
        ):
            raise ValueError("query privacy ceiling exceeds the profile policy")
        candidates = self.memory_store.embedding_candidates(
            profile_id,
            namespace=namespace,
            node_type=node_type,
            privacy_ceiling=effective_ceiling,
        )
        coverage = self.memory_store.embedding_coverage(profile_id)
        base = {
            "coverage": {
                **coverage,
                "complete": coverage["eligible_count"] == coverage["indexed_count"],
            },
            "profile_id": profile_id,
            "query": "search-semantic",
            "schema_fingerprint": self.schema.fingerprint,
            "text": query,
        }
        if not candidates:
            status = (
                "ready"
                if coverage["eligible_count"] == coverage["indexed_count"]
                else "degraded"
            )
            return {**base, "results": [], "status": status}
        try:
            provider = self._require_matching_provider(profile)
        except EmbeddingProviderError:
            return {**base, "results": [], "status": "degraded"}
        if not provider.info.configured:
            return {**base, "results": [], "status": "degraded"}
        try:
            batch = provider.embed([preprocess_text(query)])
            if batch.response_model != str(profile["model"]):
                raise EmbeddingProviderError(
                    "embedding API response model does not match the profile"
                )
            query_vector = decode_vector(
                encode_vector(batch.vectors[0], int(profile["dimensions"])),
                int(profile["dimensions"]),
            )
        except (EmbeddingProviderError, ValueError):
            return {**base, "results": [], "status": "degraded"}
        ranked = []
        for candidate in candidates:
            vector = decode_vector(
                bytes(candidate["vector_blob"]), int(profile["dimensions"])
            )
            ranked.append(
                (
                    cosine_similarity(query_vector, vector),
                    str(candidate["search_document_id"]),
                    candidate,
                )
            )
        ranked.sort(key=lambda item: (-item[0], item[1]))
        results = []
        for score, _, candidate in ranked[:limit]:
            explanation = self.explain(str(candidate["target_id"]))
            results.append(
                {
                    "attribute_name": str(candidate["attribute_name"]),
                    "content": str(candidate["content"]),
                    "content_hash": str(candidate["content_hash"]),
                    "document_id": str(candidate["search_document_id"]),
                    "fact": explanation["fact"],
                    "namespace": str(candidate["namespace"]),
                    "node_type": str(candidate["node_type"]),
                    "privacy_class": str(candidate["privacy_class"]),
                    "provenance": {
                        "assertions": explanation["assertions"],
                        "node": explanation["node"],
                    },
                    "score": score,
                    "target_id": str(candidate["target_id"]),
                    "target_kind": str(candidate["target_kind"]),
                }
            )
        status = (
            "ready"
            if coverage["eligible_count"] == coverage["indexed_count"]
            else "degraded"
        )
        return {**base, "results": results, "status": status}

    def _require_embedding_provider(self) -> EmbeddingProvider:
        if self.embedding_provider is None:
            raise EmbeddingProviderError("embedding provider is not configured")
        return self.embedding_provider

    def _provider_matches_profile(self, profile: dict[str, Any]) -> bool:
        if self.embedding_provider is None:
            return False
        info = self.embedding_provider.info
        return (
            info.provider == profile["provider"]
            and info.model == profile["model"]
            and info.dimensions == profile["dimensions"]
            and info.preprocessing_version == profile["preprocessing_version"]
            and PRIVACY_ORDER[info.privacy_ceiling]
            >= PRIVACY_ORDER[str(profile["privacy_ceiling"])]
        )

    def _require_matching_provider(self, profile: dict[str, Any]) -> EmbeddingProvider:
        provider = self._require_embedding_provider()
        if not self._provider_matches_profile(profile):
            raise EmbeddingProviderError(
                "configured embedding provider does not match the profile"
            )
        return provider

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

    def evidence_status(self, digest: str) -> dict[str, Any]:
        catalog, _ = self.memory_store.evidence_catalog(1, digest)
        if not catalog:
            raise RecordNotFoundError(f"evidence object not found: {digest}")
        status = self.evidence_store.stat(digest)
        return {
            "availability": status.availability,
            "byte_size": status.byte_size,
            "digest": digest,
            "effective_privacy": catalog[0]["object"]["privacy_class"],
            "retired": catalog[0]["retirement"] is not None,
            "verification": status.verification,
        }

    def evidence_read(
        self, digest: str, *, offset: int = 0, limit: int = 65536
    ) -> dict[str, Any]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if not 1 <= limit <= MAX_EVIDENCE_READ_BYTES:
            raise ValueError(f"limit must be between 1 and {MAX_EVIDENCE_READ_BYTES}")
        status = self.evidence_status(digest)
        if status["retired"]:
            raise FileNotFoundError(f"evidence object is retired: {digest}")
        data = self.evidence_store.read(digest, offset, limit)
        total = status["byte_size"]
        return {
            "byte_count": len(data),
            "data_base64": base64.b64encode(data).decode("ascii"),
            "digest": digest,
            "eof": total is not None and offset + len(data) >= int(total),
            "limit": limit,
            "offset": offset,
        }

    def _read_for_verification(self, digest: str, byte_size: int) -> bytes:
        if byte_size > MAX_EVIDENCE_VERIFY_BYTES:
            raise ValueError(
                "evidence object exceeds verification limit of "
                f"{MAX_EVIDENCE_VERIFY_BYTES} bytes"
            )
        chunks: list[bytes] = []
        offset = 0
        while offset < byte_size:
            chunk = self.evidence_store.read(
                digest, offset, min(MAX_EVIDENCE_READ_BYTES, byte_size - offset)
            )
            if not chunk:
                break
            chunks.append(chunk)
            offset += len(chunk)
        return b"".join(chunks)

    def evidence_verify(
        self,
        digest: str,
        *,
        checked_at: str | None = None,
        method: str = "manual-verify",
    ) -> dict[str, Any]:
        catalog, _ = self.memory_store.evidence_catalog(1, digest)
        if not catalog:
            raise RecordNotFoundError(f"evidence object not found: {digest}")
        checked = checked_at or _now()
        status = self.evidence_store.stat(digest)
        persisted = self.memory_store.record_evidence_check(
            digest,
            availability=status.availability,
            verification=status.verification,
            byte_size=status.byte_size,
            checked_at=checked,
            method=method,
        )
        fragment_results: list[dict[str, Any]] = []
        if status.verification == "verified" and status.byte_size is not None:
            data = self._read_for_verification(digest, status.byte_size)
            for fragment in catalog[0]["fragments"]:
                locator = json.loads(str(fragment["locator_json"]))
                selection = select_fragment(data, locator)
                actual_digest = sha256_bytes(selection.extracted_bytes)
                outcome = (
                    "verified"
                    if actual_digest == fragment["digest"]
                    and len(selection.extracted_bytes) == fragment["byte_size"]
                    else "corrupt"
                )
                self.memory_store.record_fragment_check(
                    str(fragment["id"]),
                    digest=actual_digest,
                    outcome=outcome,
                    byte_size=len(selection.extracted_bytes),
                    checked_at=checked,
                    method=method,
                )
                fragment_results.append(
                    {
                        "expected_digest": fragment["digest"],
                        "fragment_id": fragment["id"],
                        "outcome": outcome,
                        "reproduced_digest": actual_digest,
                    }
                )
        return {**persisted, "checked_at": checked, "fragments": fragment_results}

    def evidence_audit(
        self, *, limit: int = MAX_EVIDENCE_AUDIT_OBJECTS, checked_at: str | None = None
    ) -> dict[str, Any]:
        if not 1 <= limit <= MAX_EVIDENCE_AUDIT_OBJECTS:
            raise ValueError(
                f"limit must be between 1 and {MAX_EVIDENCE_AUDIT_OBJECTS}"
            )
        catalog, truncated = self.memory_store.evidence_catalog(limit)
        checked = checked_at or _now()
        results = [
            self.evidence_verify(
                str(item["object"]["digest"]),
                checked_at=checked,
                method="evidence-audit",
            )
            for item in catalog
        ]
        return {
            "checked_at": checked,
            "complete": not truncated,
            "results": results,
            "truncated": truncated,
        }

    def retention_report(self, *, as_of: str | None = None) -> dict[str, Any]:
        timestamp = as_of or _now()
        return {
            "as_of": timestamp,
            "objects": self.memory_store.retention_report(timestamp),
        }

    def retention_plan(
        self,
        destination: Path,
        *,
        digests: list[str] | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if destination.exists():
            raise FileExistsError(destination)
        timestamp = created_at or _now()
        report = self.memory_store.retention_report(timestamp)
        requested = None if digests is None else set(digests)
        if requested is not None:
            known = {str(item["digest"]) for item in report}
            unknown = requested - known
            if unknown:
                raise RecordNotFoundError(
                    f"unknown evidence digests: {sorted(unknown)}"
                )
        objects = [
            {
                "availability": item["availability"],
                "byte_size": item["byte_size"],
                "digest": item["digest"],
            }
            for item in report
            if item["retention_state"] == "expired"
            and item["availability"] == "present"
            and (requested is None or item["digest"] in requested)
        ]
        body: dict[str, Any] = {
            "artifact_kind": "immutable-retention-plan",
            "created_at": timestamp,
            "objects": objects,
            "reason": "retention-expired",
            "schema_fingerprint": self.schema.fingerprint,
        }
        body["plan_id"] = sha256_json(body)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(body, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return body

    def retention_retire(
        self, plan_path: Path, *, confirmation: str, retired_at: str | None = None
    ) -> dict[str, Any]:
        document = json.loads(plan_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("retention plan must be an object")
        plan_id = document.get("plan_id")
        identity = dict(document)
        identity.pop("plan_id", None)
        if plan_id != sha256_json(identity) or confirmation != plan_id:
            raise ValueError("retention plan identity or confirmation does not match")
        if document.get("schema_fingerprint") != self.schema.fingerprint:
            raise ValueError("retention plan schema fingerprint does not match")
        timestamp = retired_at or _now()
        current = {
            str(item["digest"]): item
            for item in self.memory_store.retention_report(timestamp)
        }
        retired: list[str] = []
        planned_objects = document.get("objects", [])
        if not isinstance(planned_objects, list) or not all(
            isinstance(item, dict) for item in planned_objects
        ):
            raise ValueError("retention plan objects must be an array of objects")
        for item in planned_objects:
            digest = str(item["digest"])
            state = current.get(digest)
            if state is None or state["blocking_acquisitions"]:
                raise RetentionBlockedError(
                    f"retention state changed and blocks retirement: {digest}"
                )
            status = self.evidence_store.stat(digest)
            if (
                status.availability != item["availability"]
                or status.byte_size != item["byte_size"]
            ):
                raise ValueError(
                    f"evidence state changed after retention planning: {digest}"
                )
        digests = [str(item["digest"]) for item in planned_objects]
        self.memory_store.record_retirements(
            digests,
            plan_id=str(plan_id),
            reason=str(document["reason"]),
            retired_at=timestamp,
        )
        outcomes: list[dict[str, Any]] = []
        for digest in digests:
            try:
                removed = self.evidence_store.retire(digest)
                outcomes.append(
                    {
                        "digest": digest,
                        "store_copy": "removed" if removed else "already_missing",
                        "tombstone": "recorded",
                    }
                )
            except (OSError, ValueError) as exc:
                outcomes.append(
                    {
                        "digest": digest,
                        "error": str(exc),
                        "store_copy": "removal_failed",
                        "tombstone": "recorded",
                    }
                )
            retired.append(digest)
        return {
            "outcomes": outcomes,
            "plan_id": plan_id,
            "retired_at": timestamp,
            "retired_digests": retired,
        }

    def snapshot_create(
        self, destination: Path, *, created_at: str | None = None
    ) -> dict[str, Any]:
        return create_snapshot(
            self.memory_store,
            self.evidence_store,
            self.schema,
            destination,
            created_at or _now(),
        )

    def snapshot_verify(self, source: Path) -> dict[str, Any]:
        payload = load_snapshot(source, self.schema.fingerprint)
        if self.memory_store.status().initialized:
            self.memory_store.record_artifact_check(
                "snapshot",
                str(payload.manifest["snapshot_id"]),
                digest=str(payload.manifest["snapshot_id"]),
                outcome="verified",
                byte_size=source.stat().st_size,
                checked_at=_now(),
                method="snapshot-verify",
            )
        return {
            "object_count": len(payload.manifest["objects"]),
            "row_counts": payload.manifest["row_counts"],
            "snapshot_id": payload.manifest["snapshot_id"],
            "verified": True,
        }

    def snapshot_import(self, source: Path) -> dict[str, Any]:
        payload = load_snapshot(source, self.schema.fingerprint)
        self.initialize()
        result = import_snapshot(payload, self.memory_store, self.evidence_store)
        self.memory_store.record_artifact_check(
            "import",
            str(payload.manifest["snapshot_id"]),
            digest=str(payload.manifest["snapshot_id"]),
            outcome="verified",
            byte_size=source.stat().st_size,
            checked_at=_now(),
            method="snapshot-import",
        )
        return result

    def sanitized_export(
        self,
        destination: Path,
        *,
        privacy_ceiling: str = "public",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if privacy_ceiling not in PRIVACY_ORDER:
            raise ValueError("unknown privacy ceiling")
        if destination.exists():
            raise FileExistsError(destination)
        ceiling = PRIVACY_ORDER[privacy_ceiling]
        document = {
            "artifact_kind": "sanitized-export",
            "created_at": created_at or _now(),
            "facts": [
                item
                for item in self.memory_store.current_facts()
                if PRIVACY_ORDER[str(item["privacy_class"])] <= ceiling
            ],
            "format_version": "1",
            "privacy_ceiling": privacy_ceiling,
            "relations": [
                item
                for item in self.memory_store.current_relations()
                if PRIVACY_ORDER[str(item["privacy_class"])] <= ceiling
            ],
            "restore_compatible": False,
            "schema_fingerprint": self.schema.fingerprint,
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(
                    document, stream, ensure_ascii=False, indent=2, sort_keys=True
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return document

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
                "raw_read": {
                    "enabled": True,
                    "max_bytes": MAX_EVIDENCE_READ_BYTES,
                },
                "snapshots": {"enabled": True, "format_version": "1"},
            },
            "limits": {
                "ingestion_batch_bytes": MAX_BATCH_BYTES,
                "returned_explanation_assertions": MAX_EXPLANATION_ASSERTIONS,
                "returned_query_items": MAX_QUERY_RESULTS,
                "search_results": MAX_SEARCH_RESULTS,
                "snapshot_uncompressed_bytes": MAX_SNAPSHOT_BYTES,
                "traversal_depth": MAX_TRAVERSAL_DEPTH,
                "traversal_results": MAX_TRAVERSAL_RESULTS,
                "validated_evidence_objects": MAX_VALIDATION_EVIDENCE_OBJECTS,
            },
            "logical_schema_fingerprint": self.schema.fingerprint,
            "operations": {
                "explain": {"enabled": True, "mutating": False},
                "ingestion_apply": {"enabled": True, "mutating": True},
                "ingestion_preview": {"enabled": True, "mutating": False},
                "evidence_audit": {"enabled": True, "mutating": True},
                "evidence_read": {"enabled": True, "mutating": False},
                "evidence_status": {"enabled": True, "mutating": False},
                "evidence_verify": {"enabled": True, "mutating": True},
                "query_current_facts": {"enabled": True, "mutating": False},
                "query_current_metric": {"enabled": True, "mutating": False},
                "query_current_slots": {"enabled": True, "mutating": False},
                "search_text": {"enabled": True, "mutating": False},
                "search_semantic": {"enabled": True, "mutating": False},
                "embedding_rebuild": {"enabled": True, "mutating": True},
                "traverse_relations": {"enabled": True, "mutating": False},
                "retention": {"enabled": True, "mutating": True},
                "sanitized_export": {"enabled": True, "mutating": False},
                "snapshot": {"enabled": True, "mutating": True},
            },
            "record_types": list(self.schema.document["record_types"]),
            "retrieval": {
                "full_text": {"enabled": True, "engine": "sqlite-fts5"},
                "vector": {
                    "enabled": True,
                    "mode": "exact-application-cosine",
                    "provider": (
                        None
                        if self.embedding_provider is None
                        else self.embedding_provider.info.provider
                    ),
                    "configured": bool(
                        self.embedding_provider is not None
                        and self.embedding_provider.info.configured
                    ),
                },
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
