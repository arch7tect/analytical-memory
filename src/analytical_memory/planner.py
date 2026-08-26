from __future__ import annotations

import json
import re
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
    EvidenceAcquisitionRecord,
    EvidenceBindingRecord,
    EvidenceDerivationRecord,
    EvidenceFragmentRecord,
    EvidenceLocationRecord,
    EvidenceObjectRecord,
    EvidenceVerificationRecord,
    MetricRecord,
    NodeRecord,
    PreparedEvidence,
    RelationRecord,
    RunRecord,
    SearchDocumentRecord,
    SourceRecord,
)
from analytical_memory.errors import BatchValidationError, SchemaChangedError
from analytical_memory.evidence import (
    fragment_digest,
    select_fragment,
    strictest_privacy,
)
from analytical_memory.limits import MAX_BATCH_BYTES, MAX_EVIDENCE_INGEST_BYTES
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


def _optional_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BatchValidationError(f"{field} must be a number or null")
    return float(value)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise BatchValidationError(f"{field} must be a boolean")
    return value


def _timestamp(value: object, field: str) -> str:
    try:
        return normalize_timestamp(value, field)
    except ValueError as exc:
        raise BatchValidationError(str(exc)) from exc


def _source_locator(value: object) -> str:
    locator = _text(value, "source.locator")
    if locator.startswith(("/", "~", "file://")) or re.match(
        r"^[A-Za-z]:[\\/]", locator
    ):
        raise BatchValidationError(
            "source.locator must not be an absolute machine path"
        )
    return locator


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


def _plan_assertions(
    values: object,
    prefix: str,
    *,
    target_kind: str,
    target_id: str,
    source_id: str,
    run_id: str,
    default_valid_from: str,
    default_valid_to: str | None,
    recorded_at: str,
    seen_assertions: set[str],
) -> tuple[list[AssertionRecord], list[tuple[AssertionRecord, str, float, str]]]:
    records: list[AssertionRecord] = []
    bindings: list[tuple[AssertionRecord, str, float, str]] = []
    for index, assertion_value in enumerate(_sequence(values, prefix)):
        assertion_prefix = f"{prefix}[{index}]"
        assertion_input = _mapping(assertion_value, assertion_prefix)
        stance = _text(assertion_input.get("stance"), f"{assertion_prefix}.stance")
        if stance not in STANCES:
            raise BatchValidationError(f"{assertion_prefix}.stance is invalid")
        basis = _text(assertion_input.get("basis"), f"{assertion_prefix}.basis")
        if basis not in BASES:
            raise BatchValidationError(f"{assertion_prefix}.basis is invalid")
        valid_from = _timestamp(
            assertion_input.get("valid_from", default_valid_from),
            f"{assertion_prefix}.valid_from",
        )
        valid_to_raw = assertion_input.get("valid_to", default_valid_to)
        valid_to = (
            None
            if valid_to_raw is None
            else _timestamp(valid_to_raw, f"{assertion_prefix}.valid_to")
        )
        if valid_to is not None and valid_to < valid_from:
            raise BatchValidationError(
                f"{assertion_prefix}.valid_to must not be before valid_from"
            )
        method = _text(assertion_input.get("method"), f"{assertion_prefix}.method")
        stable_key = sha256_json(
            [
                target_kind,
                target_id,
                stance,
                basis,
                source_id,
                run_id,
                valid_from,
                valid_to,
                method,
            ]
        )
        if stable_key in seen_assertions:
            raise BatchValidationError(f"duplicate assertion stable key: {stable_key}")
        seen_assertions.add(stable_key)
        record = AssertionRecord(
            id=stable_uuid("assertion", stable_key),
            target_kind=target_kind,
            target_id=target_id,
            attribute_id=target_id if target_kind == "node_attribute" else None,
            relation_id=target_id if target_kind == "relation" else None,
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
            valid_from=valid_from,
            valid_to=valid_to,
            recorded_at=recorded_at,
            method=method,
            source_id=source_id,
            run_id=run_id,
            supersedes_assertion_id=_optional_text(
                assertion_input.get("supersedes_assertion_id"),
                f"{assertion_prefix}.supersedes_assertion_id",
            ),
            lifecycle="active",
            stable_key=stable_key,
            stable_key_version=2,
        )
        records.append(record)
        bindings.append(
            (
                record,
                "supports" if stance == "supports" else "contradicts",
                record.confidence,
                record.review_status,
            )
        )
    return records, bindings


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
        locator=_source_locator(source_input.get("locator")),
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
    relation_records: list[RelationRecord] = []
    assertion_records: list[AssertionRecord] = []
    metric_records: list[MetricRecord] = []
    search_document_records: list[SearchDocumentRecord] = []
    binding_inputs: list[tuple[AssertionRecord, str, float, str]] = []
    seen_nodes: set[tuple[str, str, str]] = set()
    nodes_by_key: dict[tuple[str, str, str], NodeRecord] = {}
    seen_attributes: set[tuple[str, str, str]] = set()
    slot_cardinalities: dict[tuple[str, str], str] = {}
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
        nodes_by_key[node_key] = node

        attributes = _sequence(
            node_input.get("attributes", []), f"nodes[{node_index}].attributes"
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
            slot_key = (node.id, name)
            existing_cardinality = slot_cardinalities.get(slot_key)
            if existing_cardinality is not None and existing_cardinality != cardinality:
                raise BatchValidationError(
                    f"{prefix}.cardinality conflicts with the existing slot"
                )
            slot_cardinalities[slot_key] = cardinality
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
            searchable = _boolean(
                attribute_input.get("searchable", False), f"{prefix}.searchable"
            )
            raw_value = attribute_input.get("value")
            if searchable and not isinstance(raw_value, str):
                raise BatchValidationError(
                    f"{prefix}.value must be a string when searchable"
                )
            attribute = AttributeRecord(
                id=stable_uuid("node_attribute", *attribute_key),
                node_id=node.id,
                name=name,
                cardinality=cardinality,
                value_json=value_json,
                value_hash=value_hash,
                searchable=int(searchable),
                privacy_class=_privacy(
                    attribute_input.get("privacy_class", node.privacy_class),
                    f"{prefix}.privacy_class",
                ),
                recorded_at=recorded_at,
            )
            attribute_records.append(attribute)
            planned_assertions, planned_bindings = _plan_assertions(
                attribute_input.get("assertions", []),
                f"{prefix}.assertions",
                target_kind="node_attribute",
                target_id=attribute.id,
                source_id=source.id,
                run_id=run.id,
                default_valid_from=valid_from,
                default_valid_to=valid_to,
                recorded_at=recorded_at,
                seen_assertions=seen_assertions,
            )
            assertion_records.extend(planned_assertions)
            binding_inputs.extend(planned_bindings)

            if searchable:
                assert isinstance(raw_value, str)
                content_hash = sha256_bytes(raw_value.encode("utf-8"))
                search_document_records.append(
                    SearchDocumentRecord(
                        id=stable_uuid(
                            "search_document", attribute.id, 0, "identity-text-v1"
                        ),
                        target_kind="node_attribute",
                        target_id=attribute.id,
                        chunk_index=0,
                        content=raw_value,
                        content_hash=content_hash,
                        extraction_version="identity-text-v1",
                        privacy_class=attribute.privacy_class,
                        lifecycle="active",
                        recorded_at=recorded_at,
                    )
                )

    if not node_records:
        raise BatchValidationError("batch must contain at least one node")

    def resolve_node_reference(value: object, field: str) -> NodeRecord:
        reference = _mapping(value, field)
        key = (
            _text(reference.get("namespace"), f"{field}.namespace"),
            _text(reference.get("type"), f"{field}.type"),
            _text(reference.get("natural_key"), f"{field}.natural_key"),
        )
        try:
            return nodes_by_key[key]
        except KeyError as exc:
            raise BatchValidationError(
                f"{field} does not reference a batch node"
            ) from exc

    seen_relations: set[tuple[str, str, str, str]] = set()
    for relation_index, relation_value in enumerate(
        _sequence(payload.get("relations", []), "relations")
    ):
        prefix = f"relations[{relation_index}]"
        relation_input = _mapping(relation_value, prefix)
        source_node = resolve_node_reference(
            relation_input.get("source"), f"{prefix}.source"
        )
        target_node = resolve_node_reference(
            relation_input.get("target"), f"{prefix}.target"
        )
        relation_type = _text(relation_input.get("type"), f"{prefix}.type")
        logical_key = _text(relation_input.get("logical_key"), f"{prefix}.logical_key")
        relation_key = (
            source_node.id,
            relation_type,
            target_node.id,
            logical_key,
        )
        if relation_key in seen_relations:
            raise BatchValidationError(f"duplicate relation key: {relation_key}")
        seen_relations.add(relation_key)
        relation = RelationRecord(
            id=stable_uuid("relation", *relation_key),
            source_node_id=source_node.id,
            type=relation_type,
            target_node_id=target_node.id,
            logical_key=logical_key,
            privacy_class=_privacy(
                relation_input.get("privacy_class", "public"),
                f"{prefix}.privacy_class",
            ),
            recorded_at=recorded_at,
        )
        relation_records.append(relation)
        planned_assertions, planned_bindings = _plan_assertions(
            relation_input.get("assertions", []),
            f"{prefix}.assertions",
            target_kind="relation",
            target_id=relation.id,
            source_id=source.id,
            run_id=run.id,
            default_valid_from=valid_from,
            default_valid_to=valid_to,
            recorded_at=recorded_at,
            seen_assertions=seen_assertions,
        )
        assertion_records.extend(planned_assertions)
        binding_inputs.extend(planned_bindings)

    seen_metrics: set[tuple[str, str]] = set()
    for metric_index, metric_value in enumerate(
        _sequence(payload.get("metrics", []), "metrics")
    ):
        prefix = f"metrics[{metric_index}]"
        metric_input = _mapping(metric_value, prefix)
        definition_version = _text(
            metric_input.get("definition_version"), f"{prefix}.definition_version"
        )
        dimensions = _mapping(
            metric_input.get("dimensions", {}), f"{prefix}.dimensions"
        )
        dimensions_json = canonical_json(dimensions)
        dimensions_hash = sha256_bytes(dimensions_json.encode("utf-8"))
        metric_key = (definition_version, dimensions_hash)
        if metric_key in seen_metrics:
            raise BatchValidationError(f"duplicate metric key: {metric_key}")
        seen_metrics.add(metric_key)
        try:
            value_json = canonical_json(metric_input.get("value"))
            coverage_json = canonical_json(
                _mapping(metric_input.get("coverage", {}), f"{prefix}.coverage")
            )
        except (TypeError, ValueError) as exc:
            raise BatchValidationError(f"{prefix} contains non-canonical JSON") from exc
        complete = _boolean(metric_input.get("complete", True), f"{prefix}.complete")
        invalidated = _boolean(
            metric_input.get("invalidated", False), f"{prefix}.invalidated"
        )
        metric_records.append(
            MetricRecord(
                id=stable_uuid("metric", run.id, definition_version, dimensions_hash),
                run_id=run.id,
                definition_version=definition_version,
                value_json=value_json,
                unit=_optional_text(metric_input.get("unit"), f"{prefix}.unit"),
                numerator=_optional_number(
                    metric_input.get("numerator"), f"{prefix}.numerator"
                ),
                denominator=_optional_number(
                    metric_input.get("denominator"), f"{prefix}.denominator"
                ),
                dimensions_json=dimensions_json,
                dimensions_hash=dimensions_hash,
                method_version=_text(
                    metric_input.get("method_version"), f"{prefix}.method_version"
                ),
                coverage_json=coverage_json,
                complete=1 if complete else 0,
                invalidated=1 if invalidated else 0,
                recorded_at=recorded_at,
            )
        )

    evidence_input = _mapping(payload.get("evidence"), "evidence")
    evidence_relative_path = Path(_text(evidence_input.get("path"), "evidence.path"))
    if evidence_relative_path.is_absolute() or ".." in evidence_relative_path.parts:
        raise BatchValidationError("evidence.path must be a safe relative path")
    evidence_source_path = path.parent / evidence_relative_path
    try:
        if evidence_source_path.stat().st_size > MAX_EVIDENCE_INGEST_BYTES:
            raise BatchValidationError(
                f"evidence exceeds maximum size of {MAX_EVIDENCE_INGEST_BYTES} bytes"
            )
        evidence_bytes = evidence_source_path.read_bytes()
        if len(evidence_bytes) > MAX_EVIDENCE_INGEST_BYTES:
            raise BatchValidationError(
                f"evidence exceeds maximum size of {MAX_EVIDENCE_INGEST_BYTES} bytes"
            )
    except OSError as exc:
        raise BatchValidationError(
            f"cannot read evidence: {evidence_relative_path}"
        ) from exc
    evidence_digest = sha256_bytes(evidence_bytes)
    declared_evidence_privacy = _privacy(
        evidence_input.get("privacy_class", "public"), "evidence.privacy_class"
    )
    evidence_privacy = strictest_privacy(
        declared_evidence_privacy,
        source.privacy_class,
        *(attribute.privacy_class for attribute in attribute_records),
        *(relation.privacy_class for relation in relation_records),
    )
    evidence_object = EvidenceObjectRecord(
        id=stable_uuid("evidence_object", evidence_digest),
        digest=evidence_digest,
        byte_size=len(evidence_bytes),
        media_type=_text(evidence_input.get("media_type"), "evidence.media_type"),
        privacy_class=evidence_privacy,
        recorded_at=recorded_at,
    )
    selection = select_fragment(evidence_bytes, evidence_input.get("fragment"))
    addressed_digest = sha256_bytes(selection.addressed_bytes)
    addressed_object = evidence_object
    materialized_objects: tuple[tuple[EvidenceObjectRecord, bytes], ...] = ()
    derivations: tuple[EvidenceDerivationRecord, ...] = ()
    if addressed_digest != evidence_digest:
        addressed_object = EvidenceObjectRecord(
            id=stable_uuid("evidence_object", addressed_digest),
            digest=addressed_digest,
            byte_size=len(selection.addressed_bytes),
            media_type=(
                "application/x-ndjson"
                if selection.locator["input_format"] == "canonical-jsonl"
                else "application/json"
            ),
            privacy_class=evidence_privacy,
            recorded_at=recorded_at,
        )
        materialized_objects = ((addressed_object, selection.addressed_bytes),)
        assert selection.derivation_method is not None
        derivation_parameters = canonical_json(selection.derivation_parameters or {})
        derivations = (
            EvidenceDerivationRecord(
                id=stable_uuid(
                    "evidence_derivation",
                    evidence_object.id,
                    addressed_object.id,
                    selection.derivation_method,
                    "1",
                    derivation_parameters,
                ),
                input_object_id=evidence_object.id,
                output_object_id=addressed_object.id,
                method=selection.derivation_method,
                method_version="1",
                parameters_json=derivation_parameters,
                recorded_at=recorded_at,
            ),
        )
    locator_json = canonical_json(selection.locator)
    fragment = EvidenceFragmentRecord(
        id=stable_uuid(
            "evidence_fragment",
            addressed_object.id,
            selection.locator["kind"],
            locator_json,
            selection.extractor_id,
            selection.extractor_version,
        ),
        evidence_object_id=addressed_object.id,
        locator_kind=str(selection.locator["kind"]),
        locator_json=locator_json,
        extractor_id=selection.extractor_id,
        extractor_version=selection.extractor_version,
        byte_size=len(selection.extracted_bytes),
        digest=fragment_digest(selection),
        privacy_class=evidence_privacy,
        recorded_at=recorded_at,
    )
    retention_input = _mapping(
        evidence_input.get("retention", {}), "evidence.retention"
    )
    retention_required = _boolean(
        retention_input.get("required", False), "evidence.retention.required"
    )
    retain_until_value = retention_input.get("until")
    retain_until = (
        None
        if retain_until_value is None
        else _timestamp(retain_until_value, "evidence.retention.until")
    )
    acquisition_method = _text(
        evidence_input.get("acquisition_method", run.method),
        "evidence.acquisition_method",
    )
    acquisition_review = _text(
        evidence_input.get("review_status", "unreviewed"),
        "evidence.review_status",
    )
    all_objects = (evidence_object, *(item[0] for item in materialized_objects))
    acquisitions = tuple(
        EvidenceAcquisitionRecord(
            id=stable_uuid("evidence_acquisition", item.id, run.id),
            evidence_object_id=item.id,
            source_id=source.id,
            run_id=run.id,
            privacy_class=evidence_privacy,
            retention_required=int(retention_required),
            retain_until=retain_until,
            method=acquisition_method,
            review_status=acquisition_review,
            recorded_at=recorded_at,
        )
        for item in all_objects
    )
    locations = tuple(
        EvidenceLocationRecord(
            id=stable_uuid("evidence_location", item.id, "local-filesystem", "default"),
            evidence_object_id=item.id,
            provider="local-filesystem",
            root_id="default",
            object_key=f"objects/sha256/{item.digest[:2]}/{item.digest}",
            availability="present",
            verified_at=recorded_at,
            recorded_at=recorded_at,
        )
        for item in all_objects
    )
    verifications = tuple(
        EvidenceVerificationRecord(
            id=stable_uuid(
                "evidence_verification", item.id, recorded_at, "ingestion-put"
            ),
            target_kind="object",
            target_id=item.id,
            digest=item.digest,
            outcome="verified",
            byte_size=item.byte_size,
            method="ingestion-put",
            checked_at=recorded_at,
        )
        for item in all_objects
    )
    assertion_bindings = tuple(
        EvidenceBindingRecord(
            id=stable_uuid("evidence_binding", assertion.id, fragment.id, role),
            target_kind="assertion",
            target_id=assertion.id,
            assertion_id=assertion.id,
            metric_id=None,
            fragment_id=fragment.id,
            role=role,
            confidence=confidence,
            review_status=review_status,
            recorded_at=recorded_at,
        )
        for assertion, role, confidence, review_status in binding_inputs
    )
    metric_bindings = tuple(
        EvidenceBindingRecord(
            id=stable_uuid(
                "evidence_binding", metric.id, fragment.id, "contextualizes"
            ),
            target_kind="metric",
            target_id=metric.id,
            assertion_id=None,
            metric_id=metric.id,
            fragment_id=fragment.id,
            role="contextualizes",
            confidence=1.0,
            review_status="unreviewed",
            recorded_at=recorded_at,
        )
        for metric in metric_records
    )
    bindings = (*assertion_bindings, *metric_bindings)

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
            materialized_objects=materialized_objects,
            fragment=fragment,
            acquisitions=acquisitions,
            locations=locations,
            verifications=verifications,
            derivations=derivations,
        ),
        nodes=tuple(node_records),
        attributes=tuple(attribute_records),
        relations=tuple(relation_records),
        assertions=tuple(assertion_records),
        metrics=tuple(metric_records),
        search_documents=tuple(search_document_records),
        bindings=bindings,
    )
