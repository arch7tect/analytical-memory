from __future__ import annotations

from typing import Any

from analytical_memory.api_models import QUERY_OPERATORS
from analytical_memory.domain import QueryPlan
from analytical_memory.errors import QueryValidationError
from analytical_memory.limits import (
    MAX_QUERY_PATTERN_EDGES,
    MAX_QUERY_PATTERN_NODES,
    MAX_QUERY_RESULTS,
)

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
                "node patterns not connected by edges form a Cartesian product"
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


def _field_ref(value: object, aliases: set[str]) -> str:
    if not isinstance(value, str) or "." not in value:
        raise QueryValidationError("field references must be alias.field strings")
    alias, _, name = value.partition(".")
    if alias not in aliases or not name:
        raise QueryValidationError(f"unknown field alias: {alias}")
    return value


def parse_query_ir(document: dict[str, Any]) -> QueryPlan:
    if (
        not isinstance(document, dict)
        or document.get("query_ir_version") != QUERY_IR_VERSION
    ):
        raise QueryValidationError("query_ir_version must be '1'")
    unknown = set(document) - {
        "query_ir_version",
        "match",
        "where",
        "return",
        "order_by",
        "limit",
        "offset",
    }
    if unknown:
        raise QueryValidationError(f"unknown Query IR fields: {sorted(unknown)}")
    match = document.get("match")
    if not isinstance(match, dict):
        raise QueryValidationError("match must be an object")
    nodes = match.get("nodes")
    edges = match.get("edges", [])
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_QUERY_PATTERN_NODES:
        raise QueryValidationError("match.nodes has an invalid size")
    if not isinstance(edges, list) or len(edges) > MAX_QUERY_PATTERN_EDGES:
        raise QueryValidationError("match.edges has an invalid size")
    node_aliases: list[tuple[str, str]] = []
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {"type", "as"}:
            raise QueryValidationError("each node pattern requires type and as")
        node_aliases.append((str(node["as"]), str(node["type"])))
    aliases = {alias for alias, _ in node_aliases}
    if len(aliases) != len(node_aliases):
        raise QueryValidationError("node aliases must be unique")
    normalized_edges: list[dict[str, str]] = []
    for edge in edges:
        if not isinstance(edge, dict) or not {"type", "from", "to"} <= set(edge):
            raise QueryValidationError("each edge requires type, from, and to")
        if set(edge) - {"type", "from", "to", "logical_key"}:
            raise QueryValidationError("edge contains unknown fields")
        if edge["from"] not in aliases or edge["to"] not in aliases:
            raise QueryValidationError("edge references an unknown alias")
        normalized_edges.append({key: str(value) for key, value in edge.items()})

    predicates: list[dict[str, Any]] = []
    for predicate in document.get("where", []):
        if not isinstance(predicate, dict):
            raise QueryValidationError("where entries must be objects")
        operator = predicate.get("op")
        if operator not in QUERY_OPERATORS:
            raise QueryValidationError(f"unsupported operator: {operator}")
        left = predicate.get("left")
        if not isinstance(left, dict) or set(left) != {"field"}:
            raise QueryValidationError("predicate left side must contain field")
        normalized = {"field": _field_ref(left["field"], aliases), "op": operator}
        if operator != "exists":
            right = predicate.get("right")
            if not isinstance(right, dict):
                raise QueryValidationError("predicate right side must be an object")
            if operator == "in":
                if (
                    set(right) != {"values"}
                    or not isinstance(right["values"], list)
                    or not right["values"]
                ):
                    raise QueryValidationError("in requires right.values")
                normalized["values"] = right["values"]
            else:
                if set(right) != {"value"}:
                    raise QueryValidationError(f"{operator} requires right.value")
                normalized["value"] = right["value"]
        predicates.append(normalized)

    projections: list[dict[str, Any]] = []
    count = False
    for projection in document.get("return", []):
        if not isinstance(projection, dict):
            raise QueryValidationError("return entries must be objects")
        if projection == {"count": True}:
            count = True
            projections.append(projection)
        elif set(projection) == {"field"}:
            projections.append({"field": _field_ref(projection["field"], aliases)})
        else:
            raise QueryValidationError("return entry must contain field or count")
    if not projections:
        raise QueryValidationError("return must not be empty")
    if count and len(projections) != 1:
        raise QueryValidationError("count cannot be mixed with field projections")

    order_by: list[dict[str, str]] = []
    for order in document.get("order_by", []):
        if not isinstance(order, dict) or set(order) - {"field", "direction"}:
            raise QueryValidationError("invalid order_by entry")
        direction = order.get("direction", "asc")
        if direction not in {"asc", "desc"}:
            raise QueryValidationError("order direction must be asc or desc")
        order_by.append(
            {
                "field": _field_ref(order.get("field"), aliases),
                "direction": direction,
            }
        )
    limit = document.get("limit", DEFAULT_QUERY_LIMIT)
    offset = document.get("offset", DEFAULT_QUERY_OFFSET)
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_QUERY_RESULTS
    ):
        raise QueryValidationError(f"limit must be between 1 and {MAX_QUERY_RESULTS}")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise QueryValidationError("offset must be a non-negative integer")
    return QueryPlan(
        document=document,
        node_aliases=tuple(node_aliases),
        edges=tuple(normalized_edges),
        predicates=tuple(predicates),
        projections=tuple(projections),
        order_by=tuple(order_by),
        limit=limit,
        offset=offset,
        count=count,
    )
