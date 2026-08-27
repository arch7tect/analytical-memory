from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from analytical_memory.api_models import QueryIRDocument
from analytical_memory.domain import QueryPlan
from analytical_memory.errors import QueryValidationError

QUERY_IR_VERSION = "1"
DEFAULT_QUERY_LIMIT = 100
DEFAULT_QUERY_OFFSET = 0


def query_ir_contract_document(schema_fingerprint: str) -> dict[str, Any]:
    from analytical_memory.api_models import QueryIRDocument, QueryIRResponse

    return {
        "contract_document_version": "1",
        "query_ir_version": QUERY_IR_VERSION,
        "schema_fingerprint": schema_fingerprint,
        "input_schema": QueryIRDocument.model_json_schema(by_alias=True),
        "result_schema": QueryIRResponse.model_json_schema(by_alias=True),
        "semantics": {
            "edges": "directed active relations only",
            "field_reference": "<node-alias>.<attribute-name>",
            "missing": "no current NodeAttribute row",
            "null": "a present NodeAttribute whose JSON value is null",
            "exists": "tests attribute-row presence, so explicit null exists",
            "where": "implicit conjunction; OR is not supported",
            "not_equal": (
                "ne matches only present attributes of the effective field type; "
                "missing attributes do not match"
            ),
            "comparison": (
                "literals must match the field effective JSON type; strings and "
                "numbers are never coerced"
            ),
            "unresolved": "typed comparison produces no matches",
            "ordering": (
                "explicit fields first, present values before missing values, then "
                "every node alias ID ascending as a deterministic tie-breaker"
            ),
            "string_ordering": "Unicode casefold, then original code-point order",
            "pagination": (
                f"limit defaults to {DEFAULT_QUERY_LIMIT}, offset defaults to "
                f"{DEFAULT_QUERY_OFFSET}; truncated uses a limit-plus-one probe"
            ),
            "count": "count cannot be combined with field projections",
            "bindings": "every non-count row maps each node alias to its Node ID",
            "provenance": (
                "each field projection includes its current record, source, batch, "
                "run, evidence fragment, and update time"
            ),
            "missing_projection": (
                "a missing projected attribute has null value and null record_id; "
                "record_id distinguishes it from an explicit null value"
            ),
            "disconnected_patterns": (
                "multi-node patterns must form one connected component"
            ),
        },
        "examples": [
            {
                "query_ir_version": QUERY_IR_VERSION,
                "match": {
                    "nodes": [{"type": "example.Session", "as": "session"}],
                    "edges": [],
                },
                "where": [
                    {
                        "left": {"field": "session.status"},
                        "op": "eq",
                        "right": {"value": "failed"},
                    }
                ],
                "return": [{"field": "session.status"}],
                "limit": 100,
                "offset": 0,
            },
            {
                "query_ir_version": QUERY_IR_VERSION,
                "match": {
                    "nodes": [{"type": "example.Session", "as": "session"}],
                    "edges": [],
                },
                "return": [{"count": True}],
            },
        ],
    }


def _field_ref(value: str, aliases: set[str]) -> str:
    if "." not in value:
        raise QueryValidationError("field references must be alias.field strings")
    alias, _, name = value.partition(".")
    if alias not in aliases:
        raise QueryValidationError(f"unknown field alias: {alias}")
    if not name:
        raise QueryValidationError("field references must include an attribute name")
    return value


def parse_query_ir(document: dict[str, Any]) -> QueryPlan:
    try:
        validated = QueryIRDocument.model_validate(document)
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(item) for item in first["loc"])
        raise QueryValidationError(
            f"invalid Query IR at {location}: {first['msg']}"
        ) from exc
    canonical_document = validated.model_dump(
        mode="json",
        by_alias=True,
        exclude_unset=True,
    )
    match = canonical_document["match"]
    nodes = match["nodes"]
    edges = match.get("edges", [])
    node_aliases = [(node["as"], node["type"]) for node in nodes]
    aliases = {alias for alias, _ in node_aliases}
    if len(aliases) != len(node_aliases):
        raise QueryValidationError("node aliases must be unique")
    normalized_edges: list[dict[str, str]] = []
    for edge in edges:
        edge = dict(edge)
        if edge.get("logical_key") is None:
            edge.pop("logical_key", None)
        if edge["from"] not in aliases or edge["to"] not in aliases:
            raise QueryValidationError("edge references an unknown alias")
        normalized_edges.append(edge)

    if len(node_aliases) > 1:
        connected = {node_aliases[0][0]}
        changed = True
        while changed:
            changed = False
            for edge in normalized_edges:
                endpoints = {edge["from"], edge["to"]}
                if connected & endpoints and not endpoints <= connected:
                    connected.update(endpoints)
                    changed = True
        unreachable = sorted(aliases - connected)
        if unreachable:
            raise QueryValidationError(
                f"query pattern is disconnected; unreachable aliases: {unreachable}"
            )

    predicates: list[dict[str, Any]] = []
    for predicate in canonical_document.get("where", []):
        operator = predicate["op"]
        left = predicate["left"]
        normalized_predicate = {
            "field": _field_ref(left["field"], aliases),
            "op": operator,
        }
        if operator != "exists":
            right = predicate["right"]
            if operator == "in":
                normalized_predicate["values"] = right["values"]
            else:
                normalized_predicate["value"] = right["value"]
        predicates.append(normalized_predicate)

    projections: list[dict[str, Any]] = []
    count = False
    for projection in canonical_document.get("return", []):
        if projection == {"count": True}:
            count = True
            projections.append(projection)
        else:
            projections.append({"field": _field_ref(projection["field"], aliases)})
    if count and len(projections) != 1:
        raise QueryValidationError("count cannot be mixed with field projections")

    order_by: list[dict[str, str]] = []
    for order in canonical_document.get("order_by", []):
        direction = order.get("direction", "asc")
        order_by.append(
            {
                "field": _field_ref(order["field"], aliases),
                "direction": direction,
            }
        )
    limit = canonical_document.get("limit", DEFAULT_QUERY_LIMIT)
    offset = canonical_document.get("offset", DEFAULT_QUERY_OFFSET)
    return QueryPlan(
        node_aliases=tuple(node_aliases),
        edges=tuple(normalized_edges),
        predicates=tuple(predicates),
        projections=tuple(projections),
        order_by=tuple(order_by),
        limit=limit,
        offset=offset,
        count=count,
    )
