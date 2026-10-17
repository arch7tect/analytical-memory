"""Transactional integration for native analysis and immutable observations."""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

from analytical_memory.analytics import (
    MAX_FACTS,
    SEMANTICS,
    AnalyticsIntegrityError,
    AnalyticsLimitError,
    Evaluator,
    ObservationUnavailable,
    StaleQueryResult,
    execute_analysis,
    validate_analysis,
    validate_native_document,
    validate_query,
)
from analytical_memory.canonical import (
    canonical_json,
    sha256_bytes,
    sha256_json,
    stable_uuid,
)
from analytical_memory.domain import (
    EvidenceFragmentRecord,
    EvidenceObjectRecord,
    ImportEvidence,
)
from analytical_memory.errors import QueryValidationError, RecordNotFoundError

FACT_TABLES = (
    "node",
    "node_attribute",
    "relation",
    "entity_declaration",
    "namespace_declaration",
    "observed_field",
    "ontology_declaration",
)
CONTEXT_TABLES = ("source", "evidence_object", "evidence_fragment")
MAX_MANIFEST_BYTES = 32 * 1024 * 1024


def initialize_state(connection: Any) -> None:
    connection.execute(
        (
            "INSERT INTO memory_state (singleton, generation, data_r"
            "evision) VALUES (1, ?, 0) ON CONFLICT(singleton) DO NOT"
            "HING"
        ),
        (str(uuid.uuid4()),),
    )


def state(connection: Any) -> dict[str, Any]:
    row = connection.execute(
        "SELECT generation, data_revision FROM memory_state WHERE singleton = 1"
    ).fetchone()
    if row is None:
        raise AnalyticsIntegrityError("memory state is missing")
    return dict(row)


def fact_digest(connection: Any) -> str:
    # Declarations contribute their interpretation and privacy, not bookkeeping.
    documents = {}
    for table in FACT_TABLES:
        rows = []
        for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2"):
            item = dict(row)
            if table not in {"node", "node_attribute", "relation"}:
                for key in (
                    "source_id",
                    "fragment_id",
                    "recorded_at",
                    "first_batch_id",
                    "last_batch_id",
                ):
                    item.pop(key, None)
            for key in ("sort_text_folded", "sort_text_exact", "sort_number"):
                item.pop(key, None)
            rows.append(item)
        documents[table] = rows
    return sha256_json(documents)


def load_facts(connection: Any) -> dict[str, Any]:
    documents = {}
    total = 0
    for table in FACT_TABLES:
        rows = [
            dict(row)
            for row in connection.execute(
                f"SELECT * FROM {table} ORDER BY 1, 2 LIMIT ?", (MAX_FACTS + 1,)
            )
        ]
        total += len(rows)
        if total > MAX_FACTS:
            raise AnalyticsLimitError(
                "fact budget exceeded; narrow the memory before analysing"
            )
        documents[table] = rows

    def related(table: str, identities: set[Any]) -> list[dict[str, Any]]:
        identifiers = sorted(value for value in identities if value is not None)
        rows: list[dict[str, Any]] = []
        for start in range(0, len(identifiers), 500):
            chunk = identifiers[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(
                dict(row)
                for row in connection.execute(
                    f"SELECT * FROM {table} WHERE id IN ({placeholders})", tuple(chunk)
                )
            )
        return sorted(rows, key=lambda row: row["id"])

    source_ids = {row.get("source_id") for rows in documents.values() for row in rows}
    fragment_ids = {
        row.get("fragment_id") for rows in documents.values() for row in rows
    }
    fragments = related("evidence_fragment", fragment_ids)
    documents["evidence_fragment"] = fragments
    documents["source"] = related("source", source_ids)
    documents["evidence_object"] = related(
        "evidence_object", {row["evidence_object_id"] for row in fragments}
    )
    if sum(len(rows) for rows in documents.values()) > MAX_FACTS:
        raise AnalyticsLimitError("fact and provenance budget exceeded")
    return documents


def check_expected(current: dict[str, Any], document: dict[str, Any]) -> None:
    if document.get("expected_state") != current:
        raise StaleQueryResult(
            "generation/revision changed; refresh the analysis",
            details={
                "expected": document.get("expected_state"),
                "current": current,
                "refresh": "analysis_execute",
            },
        )


def privacy(facts: dict[str, Any]) -> str:
    # The manifest contains the bounded snapshot, so all retained fields and
    # join declarations belong to the privacy footprint, including filters.
    return (
        "private"
        if any(
            row.get("privacy_class") == "private"
            for rows in facts.values()
            for row in rows
        )
        else "public"
    )


def observation(connection: Any, observation_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM analysis_observation WHERE id = ?", (observation_id,)
    ).fetchone()
    if row is None:
        raise RecordNotFoundError(f"observation not found: {observation_id}")
    result = dict(row)
    current = state(connection)
    result["freshness"] = (
        "unknown"
        if result["generation"] != current["generation"]
        else "current"
        if result["data_revision"] == current["data_revision"]
        else "potentially_stale"
    )
    result["current_state"] = current
    return result


def validate_observation_manifest(
    obs: dict[str, Any], manifest: dict[str, Any]
) -> None:
    expected_state = {
        "generation": obs["generation"],
        "data_revision": obs["data_revision"],
    }
    identity = sha256_json(
        {
            "population_hash": obs["population_hash"],
            "definition_version": obs["definition_version"],
            "semantics": SEMANTICS,
            "state": expected_state,
            "contract_fingerprint": manifest.get("contract_fingerprint"),
        }
    )
    if (
        manifest.get("state") != expected_state
        or manifest.get("definition_version") != obs["definition_version"]
        or manifest.get("results", {}).get("population_hash") != obs["population_hash"]
        or privacy(manifest["facts"]) != obs["privacy_class"]
        or identity != obs["identity_hash"]
        or stable_uuid("analysis_observation", identity) != obs["id"]
        or stable_uuid("evidence_object", obs["manifest_digest"])
        != obs["manifest_object_id"]
    ):
        raise AnalyticsIntegrityError(
            "observation metadata disagrees with its verified manifest"
        )


def public_gate(connection: Any, obs: dict[str, Any], manifest: dict[str, Any]) -> None:
    if (
        obs["freshness"] != "current"
        or privacy(manifest["facts"]) != "public"
        or privacy(load_facts(connection)) != "public"
    ):
        raise ObservationUnavailable(
            "public use requires current verified public dependencies"
        )


def read_manifest(evidence_store: Any, digest: str) -> dict[str, Any]:
    try:
        status = evidence_store.stat(digest)
        if (
            status.availability != "present"
            or status.byte_size is None
            or status.byte_size > MAX_MANIFEST_BYTES
        ):
            raise ObservationUnavailable("immutable analysis manifest is unavailable")
        data = evidence_store.read(digest, 0, status.byte_size)
        if sha256_bytes(data) != digest:
            raise ObservationUnavailable(
                "immutable analysis manifest failed verification"
            )
        manifest = json.loads(data)
        if (
            not isinstance(manifest, dict)
            or manifest.get("format_version") != "1"
            or manifest.get("semantics") != SEMANTICS
        ):
            raise ObservationUnavailable("unsupported analysis manifest")
        return manifest
    except (OSError, ValueError) as exc:
        raise ObservationUnavailable(
            "immutable analysis manifest is unavailable"
        ) from exc


def canonical_capture_request(request: dict[str, Any]) -> dict[str, Any]:
    request = json.loads(canonical_json(request))
    for member in request["members"]:
        document = member["document"]
        document["limit"], document["offset"] = 1000, 0
        if member["kind"] == "query":
            document["order_by"] = []
    return request


def capture(
    store: Any, document: dict[str, Any], evidence_store: Any, contract_fingerprint: str
) -> dict[str, Any]:
    created: list[str] = []
    try:
        return _capture_locked(
            store, document, evidence_store, created, contract_fingerprint
        )
    except BaseException:
        # Commit failures roll back before this boundary. Reacquire the same
        # writer lock before deciding whether an exclusively created file is
        # still unreferenced; another capture may have committed it meanwhile.
        if created:
            with store._write_connection(track_revision=False) as connection:
                for digest in created:
                    if not connection.execute(
                        "SELECT id FROM evidence_object WHERE digest = ?", (digest,)
                    ).fetchone():
                        evidence_store.remove(digest)
        raise


def _capture_locked(
    store: Any,
    document: dict[str, Any],
    evidence_store: Any,
    created: list[str],
    contract_fingerprint: str,
) -> dict[str, Any]:
    if (
        set(document) != {"analysis", "expected_state", "definition_version"}
        or not isinstance(document.get("definition_version"), str)
        or not document["definition_version"].strip()
    ):
        raise QueryValidationError(
            "capture requires analysis, expected_state and a definition_version"
        )
    request = canonical_capture_request(validate_analysis(document["analysis"]))
    with store._write_connection(track_revision=False) as connection:
        current = state(connection)
        check_expected(current, document)
        facts = load_facts(connection)
        results = execute_analysis(facts, request, retain_membership=True)
        membership = results.pop("membership")
        if any(member["truncated"] for member in results["members"].values()):
            raise AnalyticsLimitError(
                "capture requires complete members within the 1000-result limit"
            )
        identity = sha256_json(
            {
                "population_hash": results["population_hash"],
                "definition_version": document["definition_version"],
                "semantics": SEMANTICS,
                "state": current,
                "contract_fingerprint": contract_fingerprint,
            }
        )
        manifest = {
            "format_version": "1",
            "semantics": SEMANTICS,
            "contract_fingerprint": contract_fingerprint,
            "state": current,
            "definition_version": document["definition_version"],
            "analysis": request,
            "results": results,
            "facts": facts,
            "membership": membership,
            "ontology": store._ontology_snapshot_connection(connection),
        }
        data = canonical_json(manifest).encode()
        if len(data) > MAX_MANIFEST_BYTES:
            raise AnalyticsLimitError("manifest byte budget exceeded")
        digest = sha256_bytes(data)
        existing = connection.execute(
            (
                "SELECT id, manifest_digest FROM analysis_observation WH"
                "ERE identity_hash = ?"
            ),
            (identity,),
        ).fetchone()
        if existing is not None:
            if existing["manifest_digest"] != digest:
                raise AnalyticsIntegrityError(
                    "capture identity has different inputs or results"
                )
            previous = observation(connection, existing["id"])
            validate_observation_manifest(
                previous, read_manifest(evidence_store, digest)
            )
            return {**previous, "replayed": True}
        from analytical_memory.adapters.sql_store import _now

        recorded_at = _now()
        classification = privacy(facts)
        obj = EvidenceObjectRecord(
            stable_uuid("evidence_object", digest),
            digest,
            len(data),
            "application/vnd.analytical-memory.analysis+json",
            classification,
            recorded_at,
        )
        fragment = EvidenceFragmentRecord(
            stable_uuid("evidence_fragment", digest, "whole_object"),
            obj.id,
            "whole_object",
            "{}",
            "native-analytics",
            SEMANTICS,
            len(data),
            digest,
            classification,
            recorded_at,
        )
        with tempfile.NamedTemporaryFile() as temporary:
            temporary.write(data)
            temporary.flush()
            put = evidence_store.put_tracked(Path(temporary.name), obj)
        if put.created:
            created.append(digest)
        run_id = stable_uuid("analytical_run", "native", identity)
        source_id = stable_uuid("source", "native", digest)
        observation_id = stable_uuid("analysis_observation", identity)
        try:
            store._upsert_provenance_entities(
                connection,
                source_id=source_id,
                source_natural_key=f"native-analysis:{digest}",
                source_kind="analytical-result",
                source_locator=f"evidence:sha256:{digest}",
                source_privacy=classification,
                recorded_at=recorded_at,
                evidence=ImportEvidence(obj, fragment, put.created),
            )
            connection.execute(
                (
                    "INSERT INTO analytical_run (id, idempotency_key, batch_"
                    "id, source_id, method, recorded_at) VALUES (?, ?, NULL,"
                    " ?, ?, ?)"
                ),
                (run_id, f"native:{identity}", source_id, SEMANTICS, recorded_at),
            )
            connection.execute(
                (
                    "INSERT INTO evidence_acquisition (id, evidence_object_i"
                    "d, source_id, run_id, privacy_class, retention_required"
                    ", retain_until, method, review_status, recorded_at) VAL"
                    "UES (?, ?, ?, ?, ?, 1, NULL, ?, 'unreviewed', ?)"
                ),
                (
                    stable_uuid("evidence_acquisition", obj.id, run_id),
                    obj.id,
                    source_id,
                    run_id,
                    classification,
                    SEMANTICS,
                    recorded_at,
                ),
            )
            connection.execute(
                (
                    "INSERT INTO evidence_location (id, evidence_object_id, "
                    "provider, root_id, object_key, availability, verified_a"
                    "t, recorded_at) VALUES (?, ?, 'local-filesystem', 'defa"
                    "ult', ?, 'present', ?, ?)"
                ),
                (
                    stable_uuid(
                        "evidence_location", obj.id, "local-filesystem", "default"
                    ),
                    obj.id,
                    f"objects/sha256/{digest[:2]}/{digest}",
                    recorded_at,
                    recorded_at,
                ),
            )
            connection.execute(
                (
                    "INSERT INTO analysis_observation (id, run_id, identity_"
                    "hash, generation, data_revision, population_hash, defin"
                    "ition_version, manifest_digest, manifest_object_id, pri"
                    "vacy_class, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?"
                    ", ?, ?, ?)"
                ),
                (
                    observation_id,
                    run_id,
                    identity,
                    current["generation"],
                    current["data_revision"],
                    results["population_hash"],
                    document["definition_version"],
                    digest,
                    obj.id,
                    classification,
                    recorded_at,
                ),
            )
            for name, member in results["members"].items():
                if member["kind"] != "query":
                    continue
                for group in member["groups"]:
                    for measure, value in {
                        **group["measures"],
                        **group["derived"],
                    }.items():
                        dimensions = {
                            "query": name,
                            "group": group["key"],
                            "measure": measure,
                        }
                        dimensions_json = canonical_json(dimensions)
                        dimensions_hash = sha256_json(dimensions)
                        connection.execute(
                            (
                                "INSERT INTO metric (id, run_id, definition_version, "
                                "val"
                                "ue_json, unit, numerator, denominator, "
                                "dimensions_json,"
                                " dimensions_hash, method_version, coverage_json, "
                                "comple"
                                "te, invalidated, fragment_id, recorded_at, origin) "
                                "VALU"
                                "ES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?, "
                                "1, 0, ?, "
                                "?, 'native')"
                            ),
                            (
                                stable_uuid("metric", run_id, dimensions_hash),
                                run_id,
                                document["definition_version"],
                                canonical_json(value),
                                dimensions_json,
                                dimensions_hash,
                                SEMANTICS,
                                canonical_json(results["coverage"]),
                                fragment.id,
                                recorded_at,
                            ),
                        )
            # Verify the exact bytes before the commit while retaining the state lock.
            read_manifest(evidence_store, digest)
            check_expected(state(connection), document)
        except Exception:
            # Newly created files are ours; the lock excludes another capture
            # installing the same manifest until this transaction rolls back.
            if put.created:
                evidence_store.remove(digest)
            raise
        return {**observation(connection, observation_id), "replayed": False}


def drill(
    facts: dict[str, Any], query: dict[str, Any], document: dict[str, Any]
) -> dict[str, Any]:
    evaluator = Evaluator(facts)
    result, membership = evaluator.aggregate(query)
    key = document.get("group_key")
    matches = [
        identity
        for identity, members in membership.items()
        if identity
        == sha256_json({"population_hash": result["population_hash"], "group_key": key})
    ]
    if len(matches) != 1:
        raise QueryValidationError("unknown typed group key")
    identity = matches[0]
    members = membership[identity]
    measure_name = document.get("measure")
    measures = {item["as"]: item for item in query["measures"]}
    ratios = {item["as"]: item for item in query["derive"]}
    if measure_name not in measures and measure_name not in ratios:
        raise QueryValidationError("unknown measure")
    view = document.get("view", "counted_entities")
    if measure_name in ratios:
        if view not in {"numerator", "denominator", "bindings", "provenance"}:
            raise QueryValidationError(
                "ratio detail requires numerator or denominator view"
            )
        measure_name = ratios[measure_name][
            "denominator" if view == "denominator" else "numerator"
        ]
    measure = measures[measure_name]
    selected = evaluator.selected(members, measure)
    owner = (
        measure["node"]
        if measure["op"] != "sum"
        else measure["field"].partition(".")[0]
    )
    if view == "denominator" and document.get("measure") not in ratios:
        raise QueryValidationError("denominator view requires a ratio")
    contributions: dict[str, dict[str, Any]] = {}
    if measure["op"] == "sum":
        from analytical_memory.analytics import checked_integer

        for binding in selected:
            row = evaluator.field(binding, measure["field"])
            value = None if row is None else json.loads(row["value_json"])
            if value is None:
                continue
            node_id = binding[owner]
            entry = contributions.setdefault(
                node_id, {"value": checked_integer(value), "occurrences": 0}
            )
            entry["occurrences"] += 1
        for entry in contributions.values():
            contribution = entry["value"] * (
                1 if measure["distinct_on"] else entry["occurrences"]
            )
            from analytical_memory.analytics import SAFE_INTEGER

            entry["contribution"] = (
                contribution if abs(contribution) <= SAFE_INTEGER else str(contribution)
            )
            if isinstance(entry["contribution"], str):
                entry["contribution_encoding"] = "decimal_integer_string"
    if view == "bindings":
        rows: list[dict[str, Any]] = sorted(selected, key=canonical_json)
    elif view in {"counted_entities", "numerator", "denominator", "provenance"}:
        ids = (
            sorted(contributions)
            if measure["op"] == "sum"
            else sorted({row[owner] for row in selected if row[owner] is not None})
        )
        rows = [
            {
                "node": evaluator.nodes[node_id],
                "attributes": [
                    {**row, "value": json.loads(row["value_json"])}
                    for row in facts["node_attribute"]
                    if row["node_id"] == node_id
                ],
            }
            for node_id in ids
        ]
    else:
        raise QueryValidationError("unsupported drill-down view")
    if view == "provenance":
        sources = {row["id"]: row for row in facts["source"]}
        fragments = {row["id"]: row for row in facts["evidence_fragment"]}
        objects = {row["id"]: row for row in facts["evidence_object"]}
        for row in rows:
            for attribute in row["attributes"]:
                fragment = fragments.get(attribute["fragment_id"])
                attribute["provenance"] = {
                    "source": sources.get(attribute["source_id"]),
                    "fragment": fragment,
                    "evidence_object": None
                    if fragment is None
                    else objects.get(fragment["evidence_object_id"]),
                }
    start, limit = document.get("offset", 0), document.get("limit", 100)
    if (
        type(start) is not int
        or start < 0
        or type(limit) is not int
        or not 1 <= limit <= 1000
    ):
        raise QueryValidationError("invalid drill-down pagination")
    return {
        "group_id": identity,
        "population_hash": result["population_hash"],
        "measure": measure_name,
        "view": view,
        "rows": rows[start : start + limit],
        "total_members": len(rows),
        "truncated": start + limit < len(rows),
        "ordering": "node_id_or_canonical_binding_ascending",
        "reconciliation": {
            "op": measure["op"],
            "sum_contributions": contributions,
            "binding_count": len(selected),
            "distinct_entities": len(
                {row[owner] for row in selected if row[owner] is not None}
            ),
        },
    }


def raw_source_statuses(
    facts: dict[str, Any], detail: dict[str, Any], evidence_store: Any
) -> list[dict[str, Any]]:
    identifiers = set()
    for row in detail["rows"]:
        if "node" in row:
            identifiers.add(row["node"]["id"])
        else:
            identifiers.update(
                value for value in row.values() if isinstance(value, str)
            )
    fragments = {
        row["fragment_id"]
        for row in facts["node_attribute"]
        if row["node_id"] in identifiers
    }
    objects = {
        row["evidence_object_id"]
        for row in facts["evidence_fragment"]
        if row["id"] in fragments
    }
    results, remaining = [], 8 * 1024 * 1024
    for obj in facts["evidence_object"]:
        if obj["id"] not in objects:
            continue
        if obj["byte_size"] > remaining:
            results.append(
                {
                    "digest": obj["digest"],
                    "availability": "unknown",
                    "verification": "unverified",
                    "reason": "source_verification_byte_budget",
                }
            )
            continue
        remaining -= obj["byte_size"]
        status = evidence_store.stat(obj["digest"])
        results.append(
            {
                "digest": obj["digest"],
                "availability": status.availability,
                "verification": status.verification,
            }
        )
    return results


def operate(
    store: Any,
    operation: str,
    document: dict[str, Any],
    evidence_store: Any,
    contract_fingerprint: str,
) -> dict[str, Any]:
    document = validate_native_document(operation, document)
    if operation == "analysis_capture":
        return capture(store, document, evidence_store, contract_fingerprint)
    with store._read_connection() as connection:
        current = state(connection)
        if operation == "data_state":
            return current
        if operation == "analysis_read":
            obs = observation(connection, document["observation_id"])
            if document.get("fresh_only") and obs["freshness"] != "current":
                raise StaleQueryResult("observation is not current")
            manifest = read_manifest(evidence_store, obs["manifest_digest"])
            validate_observation_manifest(obs, manifest)
            if document.get("public"):
                public_gate(connection, obs, manifest)
            return {
                "observation": obs,
                "results": manifest["results"],
                "verified": True,
            }
        saved = operation == "query_drill_down" and "observation_id" in document
        if saved:
            obs = observation(connection, document["observation_id"])
            manifest = read_manifest(evidence_store, obs["manifest_digest"])
            validate_observation_manifest(obs, manifest)
            if document.get("public"):
                public_gate(connection, obs, manifest)
            matches = [
                item
                for item in manifest["analysis"]["members"]
                if item["name"] == document.get("query_name")
                and item["kind"] == "query"
            ]
            if len(matches) != 1:
                raise QueryValidationError(
                    "saved drill requires an exact query member name"
                )
            detail = drill(manifest["facts"], matches[0]["document"], document)
            return {
                **detail,
                "raw_source_evidence": raw_source_statuses(
                    manifest["facts"], detail, evidence_store
                ),
                "observation": obs,
                "mode": "observation_time",
                "state": manifest["state"],
                "raw_source_availability": "reported_separately_from_manifest",
            }
        if operation in {"query_drill_down", "relation_inspect"}:
            check_expected(current, document)
        facts = load_facts(connection)
        if document.get("public") and privacy(facts) != "public":
            raise ObservationUnavailable(
                "public drill-down requires public dependencies"
            )
        ontology = store._ontology_snapshot_connection(connection)
        if operation == "query_execute_v2":
            result, _ = Evaluator(facts).aggregate(validate_query(document))
        elif operation == "analysis_execute":
            result = execute_analysis(facts, validate_analysis(document))
        elif operation == "relation_inspect":
            result = Evaluator(facts).inspect(
                {
                    key: value
                    for key, value in document.items()
                    if key != "expected_state"
                }
            )
        elif operation == "query_drill_down":
            result = drill(facts, validate_query(document["query"]), document)
        else:
            raise QueryValidationError("unknown native operation")
        return {
            **result,
            "state": current,
            "ontology_fingerprint": ontology["ontology_fingerprint"],
        }
