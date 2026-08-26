from __future__ import annotations

from typing import Any

from analytical_memory.domain import QueryPlan
from analytical_memory.errors import QueryValidationError
from analytical_memory.limits import (
    MAX_QUERY_PATTERN_EDGES,
    MAX_QUERY_PATTERN_NODES,
    MAX_QUERY_RESULTS,
)

OPERATORS = {"eq", "ne", "lt", "lte", "gt", "gte", "in", "exists"}


def _field_ref(value: object, aliases: set[str]) -> str:
    if not isinstance(value, str) or "." not in value:
        raise QueryValidationError("field references must be alias.field strings")
    alias, _, name = value.partition(".")
    if alias not in aliases or not name:
        raise QueryValidationError(f"unknown field alias: {alias}")
    return value


def parse_query_ir(document: dict[str, Any]) -> QueryPlan:
    if not isinstance(document, dict) or document.get("query_ir_version") != "1":
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
        if operator not in OPERATORS:
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
                if set(right) != {"values"} or not isinstance(right["values"], list):
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
    limit = document.get("limit", 100)
    offset = document.get("offset", 0)
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
