from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analytical_memory.canonical import (
    canonical_json,
    normalize_timestamp,
    sha256_bytes,
    sha256_json,
    stable_uuid,
)
from analytical_memory.domain import (
    AssertionRecord,
    AttributeRecord,
    BatchPlan,
    EvidenceBindingRecord,
    EvidenceFragmentRecord,
    EvidenceObjectRecord,
    NodeRecord,
    PreparedEvidence,
    RunRecord,
    SourceRecord,
)
from analytical_memory.errors import BatchValidationError, SchemaChangedError
from analytical_memory.limits import MAX_BATCH_BYTES
from analytical_memory.schema_contract import SchemaContract

PRIVACY_CLASSES = {"public", "private", "restricted", "forbidden"}
STANCES = {"supports", "contradicts"}
BASES = {"observed", "computed", "inferred", "declared"}
CARDINALITIES = {"single", "multi"}


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise BatchValidationError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise BatchValidationError(f"{field} must be an array")
    return value


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise BatchValidationError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _privacy(value: object, field: str) -> str:
    privacy = _text(value, field)
    if privacy not in PRIVACY_CLASSES:
        raise BatchValidationError(f"{field} has an unknown privacy class")
    return privacy


def _confidence(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BatchValidationError(f"{field} must be a number")
    confidence = float(value)
    if not 0.0 <= confidence <= 1.0:
        raise BatchValidationError(f"{field} must be between 0 and 1")
    return confidence


def _timestamp(value: object, field: str) -> str:
    try:
        return normalize_timestamp(value, field)
    except ValueError as exc:
        raise BatchValidationError(str(exc)) from exc


def _load_document(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        if len(payload) > MAX_BATCH_BYTES:
            raise BatchValidationError(
                f"batch exceeds maximum size of {MAX_BATCH_BYTES} bytes"
            )
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BatchValidationError(f"cannot read batch: {path}") from exc
    return _mapping(value, "batch")


def plan_batch(path: Path, schema: SchemaContract) -> BatchPlan:
    payload = _load_document(path)
    supplied_fingerprint = _text(
        payload.get("schema_fingerprint"), "schema_fingerprint"
    )
    if supplied_fingerprint != schema.fingerprint:
        raise SchemaChangedError(supplied_fingerprint, schema.fingerprint)

    idempotency_key = _text(payload.get("idempotency_key"), "idempotency_key")
    recorded_at = _timestamp(payload.get("recorded_at"), "recorded_at")
    batch_id = stable_uuid("ingestion_batch", idempotency_key)

    source_input = _mapping(payload.get("source"), "source")
    source_natural_key = _text(source_input.get("natural_key"), "source.natural_key")
    source = SourceRecord(
        id=stable_uuid("source", source_natural_key),
        natural_key=source_natural_key,
        kind=_text(source_input.get("kind"), "source.kind"),
        locator=_text(source_input.get("locator"), "source.locator"),
        privacy_class=_privacy(
            source_input.get("privacy_class", "public"), "source.privacy_class"
        ),
        recorded_at=recorded_at,
    )

    run_input = _mapping(payload.get("run"), "run")
    run_idempotency_key = f"{idempotency_key}:run"
    valid_from = _timestamp(run_input.get("valid_from"), "run.valid_from")
    valid_to_raw = run_input.get("valid_to")
    valid_to = (
        None if valid_to_raw is None else _timestamp(valid_to_raw, "run.valid_to")
    )
    if valid_to is not None and valid_to < valid_from:
        raise BatchValidationError("run.valid_to must not be before run.valid_from")
    run = RunRecord(
        id=stable_uuid("analytical_run", run_idempotency_key),
        idempotency_key=run_idempotency_key,
        batch_id=batch_id,
        source_id=source.id,
        valid_from=valid_from,
        valid_to=valid_to,
        method=_text(run_input.get("method"), "run.method"),
        recorded_at=recorded_at,
    )

    node_records: list[NodeRecord] = []
    attribute_records: list[AttributeRecord] = []
    assertion_records: list[AssertionRecord] = []
    binding_inputs: list[tuple[AssertionRecord, str, float, str]] = []
    seen_nodes: set[tuple[str, str, str]] = set()
    seen_attributes: set[tuple[str, str, str]] = set()
    seen_assertions: set[str] = set()

    for node_index, node_value in enumerate(_sequence(payload.get("nodes"), "nodes")):
        node_input = _mapping(node_value, f"nodes[{node_index}]")
        namespace = _text(node_input.get("namespace"), f"nodes[{node_index}].namespace")
        node_type = _text(node_input.get("type"), f"nodes[{node_index}].type")
        natural_key = _text(
            node_input.get("natural_key"), f"nodes[{node_index}].natural_key"
        )
        node_key = (namespace, node_type, natural_key)
        if node_key in seen_nodes:
            raise BatchValidationError(f"duplicate node key: {node_key}")
        seen_nodes.add(node_key)
        node = NodeRecord(
            id=stable_uuid("node", *node_key),
            namespace=namespace,
            type=node_type,
            natural_key=natural_key,
            display_label=_optional_text(
                node_input.get("display_label"), f"nodes[{node_index}].display_label"
            ),
            privacy_class=_privacy(
                node_input.get("privacy_class", "public"),
                f"nodes[{node_index}].privacy_class",
            ),
            recorded_at=recorded_at,
        )
        node_records.append(node)

        attributes = _sequence(
            node_input.get("attributes"), f"nodes[{node_index}].attributes"
        )
        for attribute_index, attribute_value in enumerate(attributes):
            prefix = f"nodes[{node_index}].attributes[{attribute_index}]"
            attribute_input = _mapping(attribute_value, prefix)
            name = _text(attribute_input.get("name"), f"{prefix}.name")
            cardinality = _text(
                attribute_input.get("cardinality"), f"{prefix}.cardinality"
            )
            if cardinality not in CARDINALITIES:
                raise BatchValidationError(f"{prefix}.cardinality is invalid")
            try:
                value_json = canonical_json(attribute_input.get("value"))
            except (TypeError, ValueError) as exc:
                raise BatchValidationError(
                    f"{prefix}.value is not canonical JSON"
                ) from exc
            value_hash = sha256_bytes(value_json.encode("utf-8"))
            attribute_key = (node.id, name, value_hash)
            if attribute_key in seen_attributes:
                raise BatchValidationError(f"duplicate attribute key: {attribute_key}")
            seen_attributes.add(attribute_key)
            attribute = AttributeRecord(
                id=stable_uuid("node_attribute", *attribute_key),
                node_id=node.id,
                name=name,
                cardinality=cardinality,
                value_json=value_json,
                value_hash=value_hash,
                privacy_class=_privacy(
                    attribute_input.get("privacy_class", node.privacy_class),
                    f"{prefix}.privacy_class",
                ),
                recorded_at=recorded_at,
            )
            attribute_records.append(attribute)

            assertions = _sequence(
                attribute_input.get("assertions", []), f"{prefix}.assertions"
            )
            for assertion_index, assertion_value in enumerate(assertions):
                assertion_prefix = f"{prefix}.assertions[{assertion_index}]"
                assertion_input = _mapping(assertion_value, assertion_prefix)
                stance = _text(
                    assertion_input.get("stance"), f"{assertion_prefix}.stance"
                )
                if stance not in STANCES:
                    raise BatchValidationError(f"{assertion_prefix}.stance is invalid")
                basis = _text(assertion_input.get("basis"), f"{assertion_prefix}.basis")
                if basis not in BASES:
                    raise BatchValidationError(f"{assertion_prefix}.basis is invalid")
                assertion_valid_from = _timestamp(
                    assertion_input.get("valid_from", valid_from),
                    f"{assertion_prefix}.valid_from",
                )
                assertion_valid_to_raw = assertion_input.get("valid_to", valid_to)
                assertion_valid_to = (
                    None
                    if assertion_valid_to_raw is None
                    else _timestamp(
                        assertion_valid_to_raw, f"{assertion_prefix}.valid_to"
                    )
                )
                method = _text(
                    assertion_input.get("method"), f"{assertion_prefix}.method"
                )
                stable_key = sha256_json(
                    [
                        attribute.id,
                        stance,
                        basis,
                        source.id,
                        run.id,
                        assertion_valid_from,
                        assertion_valid_to,
                        method,
                    ]
                )
                if stable_key in seen_assertions:
                    raise BatchValidationError(
                        f"duplicate assertion stable key: {stable_key}"
                    )
                seen_assertions.add(stable_key)
                assertion = AssertionRecord(
                    id=stable_uuid("assertion", stable_key),
                    attribute_id=attribute.id,
                    stance=stance,
                    basis=basis,
                    confidence=_confidence(
                        assertion_input.get("confidence", 1.0),
                        f"{assertion_prefix}.confidence",
                    ),
                    review_status=_text(
                        assertion_input.get("review_status", "unreviewed"),
                        f"{assertion_prefix}.review_status",
                    ),
                    valid_from=assertion_valid_from,
                    valid_to=assertion_valid_to,
                    recorded_at=recorded_at,
                    method=method,
                    source_id=source.id,
                    run_id=run.id,
                    supersedes_assertion_id=_optional_text(
                        assertion_input.get("supersedes_assertion_id"),
                        f"{assertion_prefix}.supersedes_assertion_id",
                    ),
                    lifecycle="active",
                    stable_key=stable_key,
                )
                assertion_records.append(assertion)
                binding_inputs.append(
                    (
                        assertion,
                        "supports" if stance == "supports" else "contradicts",
                        assertion.confidence,
                        assertion.review_status,
                    )
                )

    if not node_records or not attribute_records:
        raise BatchValidationError("batch must contain at least one node and attribute")

    evidence_input = _mapping(payload.get("evidence"), "evidence")
    evidence_relative_path = Path(_text(evidence_input.get("path"), "evidence.path"))
    if evidence_relative_path.is_absolute() or ".." in evidence_relative_path.parts:
        raise BatchValidationError("evidence.path must be a safe relative path")
    evidence_source_path = path.parent / evidence_relative_path
    try:
        evidence_bytes = evidence_source_path.read_bytes()
    except OSError as exc:
        raise BatchValidationError(
            f"cannot read evidence: {evidence_relative_path}"
        ) from exc
    evidence_digest = sha256_bytes(evidence_bytes)
    evidence_privacy = _privacy(
        evidence_input.get("privacy_class", "public"), "evidence.privacy_class"
    )
    evidence_object = EvidenceObjectRecord(
        id=stable_uuid("evidence_object", evidence_digest),
        digest=evidence_digest,
        byte_size=len(evidence_bytes),
        media_type=_text(evidence_input.get("media_type"), "evidence.media_type"),
        privacy_class=evidence_privacy,
        recorded_at=recorded_at,
    )
    locator_json = canonical_json({"kind": "whole_object"})
    fragment = EvidenceFragmentRecord(
        id=stable_uuid(
            "evidence_fragment",
            evidence_object.id,
            "whole_object",
            locator_json,
            "identity",
            "1",
        ),
        evidence_object_id=evidence_object.id,
        locator_kind="whole_object",
        locator_json=locator_json,
        extractor_id="identity",
        extractor_version="1",
        byte_size=len(evidence_bytes),
        digest=evidence_digest,
        privacy_class=evidence_privacy,
        recorded_at=recorded_at,
    )
    bindings = tuple(
        EvidenceBindingRecord(
            id=stable_uuid("evidence_binding", assertion.id, fragment.id, role),
            assertion_id=assertion.id,
            fragment_id=fragment.id,
            role=role,
            confidence=confidence,
            review_status=review_status,
            recorded_at=recorded_at,
        )
        for assertion, role, confidence, review_status in binding_inputs
    )

    normalized_input = dict(payload)
    normalized_evidence = dict(evidence_input)
    normalized_evidence.pop("path", None)
    normalized_evidence["digest"] = evidence_digest
    normalized_evidence["byte_size"] = len(evidence_bytes)
    normalized_input["evidence"] = normalized_evidence
    input_hash = sha256_json(normalized_input)

    return BatchPlan(
        id=batch_id,
        idempotency_key=idempotency_key,
        input_hash=input_hash,
        schema_fingerprint=schema.fingerprint,
        recorded_at=recorded_at,
        source=source,
        run=run,
        evidence=PreparedEvidence(
            source_path=evidence_source_path,
            object=evidence_object,
            fragment=fragment,
        ),
        nodes=tuple(node_records),
        attributes=tuple(attribute_records),
        assertions=tuple(assertion_records),
        bindings=bindings,
    )
