"""Bounded, backend-neutral native Query IR v2 evaluation.

Facts are supplied by the store in one database snapshot. This module never
reads a database, performs a mutation, or approximates an incomplete population.
"""

from __future__ import annotations

import json
import math
import time
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction
from functools import cmp_to_key
from itertools import product
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from analytical_memory.api_models import APIModel
from analytical_memory.canonical import canonical_json, sha256_json
from analytical_memory.errors import QueryValidationError
from analytical_memory.jsonl import json_type
from analytical_memory.query_ir import parse_query_ir

MAX_FACTS = 50_000
MAX_BINDINGS = 100_000
MAX_SECONDS = 10
MAX_MEMBERS = 16
SAFE_INTEGER = 2**53 - 1
SEMANTICS = "native-analytics-1"


class AnalyticsError(QueryValidationError):
    """A typed failure; never a partial analytical result."""

    code = "analytics_error"


class StaleQueryResult(AnalyticsError):
    code = "stale_query_result"
    retryable = True


class AnalyticsLimitError(AnalyticsError):
    code = "analytics_limit_exceeded"


class AnalyticsIntegrityError(AnalyticsError):
    code = "analytics_integrity_error"


class ObservationUnavailable(AnalyticsError):
    code = "observation_unavailable"


class OptionalPattern(APIModel):
    nodes: list[dict[str, str]] = Field(min_length=1, max_length=1)
    edges: list[dict[str, str]] = Field(min_length=1, max_length=1)
    where: list[dict[str, Any]] = Field(default_factory=list, max_length=32)


class GroupField(APIModel):
    field: str
    as_: str = Field(alias="as", min_length=1)


class BindingCondition(APIModel):
    bound: str | None = None
    unbound: str | None = None

    @model_validator(mode="after")
    def one_condition(self) -> BindingCondition:
        if (self.bound is None) == (self.unbound is None):
            raise ValueError("exactly one bound or unbound alias is required")
        return self


class Measure(APIModel):
    as_: str = Field(alias="as", min_length=1)
    op: Literal["count", "count_distinct", "sum"]
    node: str | None = None
    field: str | None = None
    distinct_on: str | None = None
    when: BindingCondition | None = None


class Ratio(APIModel):
    as_: str = Field(alias="as", min_length=1)
    op: Literal["ratio"]
    numerator: str
    denominator: str
    zero_denominator: Literal["null"] = "null"


class ResultOrdering(APIModel):
    result: str
    direction: Literal["asc", "desc"] = "asc"


class QueryIRV2Document(APIModel):
    query_ir_version: Literal["2"]
    match: dict[str, Any]
    where: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    optional_match: list[OptionalPattern] = Field(default_factory=list, max_length=1)
    group_by: list[GroupField] = Field(default_factory=list, max_length=8)
    measures: list[Measure] = Field(min_length=1, max_length=32)
    derive: list[Ratio] = Field(default_factory=list, max_length=16)
    order_by: list[ResultOrdering] = Field(default_factory=list, max_length=16)
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class AnalyticsResponse(APIModel):
    """Versioned envelope shared by native operations, separate from v1 rows."""

    format_version: Literal["1"] = "1"
    result: dict[str, Any]


class AnalysisMember(APIModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["query", "relation_inspection"]
    document: dict[str, Any]


class AnalysisRequest(APIModel):
    members: list[AnalysisMember] = Field(min_length=1, max_length=MAX_MEMBERS)
    coverage_scope: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_names(self) -> AnalysisRequest:
        names = [item.name for item in self.members]
        if len(set(names)) != len(names):
            raise ValueError("analysis member names must be unique")
        for reference in self.coverage_scope.values():
            if not isinstance(reference, dict) or set(reference) != {
                "member",
                "measure",
            }:
                raise ValueError("coverage roles require member and measure references")
            if reference["member"] not in names:
                raise ValueError("coverage role references an unknown member")
        return self


def validate_query(document: dict[str, Any]) -> dict[str, Any]:
    try:
        query = QueryIRV2Document.model_validate(document).model_dump(
            mode="json", by_alias=True
        )
    except ValidationError as exc:
        raise QueryValidationError(str(exc)) from exc
    base = parse_query_ir(
        {
            "query_ir_version": "1",
            "return": [{"count": True}],
            "match": query["match"],
            "where": query["where"],
        }
    )
    aliases = {name for name, _ in base.node_aliases}
    base_aliases = set(aliases)
    for optional in query["optional_match"]:
        nodes, edges = optional["nodes"], optional["edges"]
        if set(nodes[0]) != {"as", "type"}:
            raise QueryValidationError("optional node requires exactly as and type")
        alias = nodes[0]["as"]
        if alias in aliases:
            raise QueryValidationError("optional alias must be new")
        edge = edges[0]
        if set(edge) != {"from", "to", "type", "logical_key"}:
            raise QueryValidationError("optional edge requires an exact logical_key")
        if (
            alias not in {edge["from"], edge["to"]}
            or not ({edge["from"], edge["to"]} - {alias}) <= base_aliases
            or edge["from"] == edge["to"]
        ):
            raise QueryValidationError(
                "optional pattern must be anchored to the required pattern"
            )
        parse_query_ir(
            {
                "query_ir_version": "1",
                "return": [{"count": True}],
                "match": {
                    "nodes": [*query["match"]["nodes"], nodes[0]],
                    "edges": [*query["match"].get("edges", []), edge],
                },
                "where": optional["where"],
            }
        )
        aliases.add(alias)
    names: set[str] = set()
    for item in [*query["group_by"], *query["measures"], *query["derive"]]:
        if item["as"] in names:
            raise QueryValidationError("result aliases must be unique")
        names.add(item["as"])
    for group in query["group_by"]:
        owner, separator, field = group["field"].partition(".")
        if owner not in base_aliases or not separator or not field:
            raise QueryValidationError("group_by requires a base scalar field")
    for measure in query["measures"]:
        if measure["op"] == "sum":
            owner, separator, field = (measure["field"] or "").partition(".")
            if (
                owner not in aliases
                or not separator
                or not field
                or measure["node"] is not None
            ):
                raise QueryValidationError("sum requires a field, without node")
            if measure["distinct_on"] not in (None, owner):
                raise QueryValidationError(
                    "distinct_on must equal the summed field owner"
                )
        elif (
            measure["node"] not in aliases
            or measure["field"] is not None
            or measure["distinct_on"] is not None
        ):
            raise QueryValidationError("count requires a bound node alias only")
        when = measure["when"]
        if (
            when
            and next(value for value in when.values() if value is not None)
            not in aliases - base_aliases
        ):
            raise QueryValidationError("when requires an optional alias")
    measures = {item["as"] for item in query["measures"]}
    for ratio in query["derive"]:
        if ratio["numerator"] not in measures or ratio["denominator"] not in measures:
            raise QueryValidationError("ratios reference named integer measures")
    if any(order["result"] not in names for order in query["order_by"]):
        raise QueryValidationError("ordering references an unknown result")
    return query


def population_hash(query: dict[str, Any]) -> str:
    return sha256_json(
        {
            "semantics": SEMANTICS,
            "query": {
                key: value
                for key, value in query.items()
                if key not in {"limit", "offset", "order_by"}
            },
        }
    )


def checked_integer(value: Any) -> int:
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        value = int(value)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or abs(value) > SAFE_INTEGER
    ):
        raise AnalyticsError(
            "unsafe_numeric_value: integer-valued JSON within ±(2^53-1) required"
        )
    return value


def typed(value: Any, *, present: bool = True) -> dict[str, Any]:
    if not present:
        return {"kind": "missing"}
    if value is None:
        return {"kind": "null"}
    if isinstance(value, (list, dict)):
        raise QueryValidationError("group keys must be scalar")
    kind = (
        "boolean"
        if isinstance(value, bool)
        else "number"
        if isinstance(value, (int, float))
        else "string"
    )
    return {"kind": "value", "type": kind, "value": value}


class Evaluator:
    def __init__(self, facts: dict[str, Any]) -> None:
        self.facts = facts
        self.nodes = {row["id"]: row for row in facts["node"]}
        self.attrs = {
            (row["node_id"], row["attribute_name"]): row
            for row in facts["node_attribute"]
        }
        self.relations = [row for row in facts["relation"] if row["active"]]
        self.deadline = time.monotonic() + MAX_SECONDS
        self.work = 0

    def tick(self, amount: int = 1) -> None:
        self.work += amount
        if self.work > MAX_BINDINGS or time.monotonic() > self.deadline:
            raise AnalyticsLimitError("binding/time budget exceeded; no partial result")

    def field(self, binding: dict[str, Any], field: str) -> dict[str, Any] | None:
        alias, _, name = field.partition(".")
        return self.attrs.get((binding.get(alias), name))

    def predicates(
        self, binding: dict[str, Any], predicates: list[dict[str, Any]]
    ) -> bool:
        for predicate in predicates:
            row = self.field(binding, predicate["left"]["field"])
            op = predicate["op"]
            if op == "exists":
                if row is None:
                    return False
                continue
            if row is None:
                return False
            value = json.loads(row["value_json"])
            right = predicate["right"]
            candidates = right["values"] if op == "in" else [right["value"]]

            def equal(other: Any, value: Any = value) -> bool:
                return json_type(value) == json_type(other) and canonical_json(
                    value
                ) == canonical_json(other)

            if op in {"eq", "in"} and not any(equal(item) for item in candidates):
                return False
            if op == "ne" and (
                json_type(value) != json_type(candidates[0]) or equal(candidates[0])
            ):
                return False
            if op in {"lt", "lte", "gt", "gte"}:
                other = candidates[0]
                if (
                    value is None
                    or other is None
                    or json_type(value) != json_type(other)
                ):
                    return False
                if isinstance(value, (dict, list, bool)):
                    raise QueryValidationError(
                        "ordered comparison requires a string or number"
                    )
                if not {
                    "lt": value < other,
                    "lte": value <= other,
                    "gt": value > other,
                    "gte": value >= other,
                }[op]:
                    return False
        return True

    def bindings(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        def candidates(node: dict[str, Any]) -> list[str]:
            return sorted(
                row["id"]
                for row in self.nodes.values()
                if f"{row['namespace']}.{row['type']}" == node["type"]
            )

        def edge_count(binding: dict[str, Any], edges: list[dict[str, Any]]) -> int:
            count = 1
            for edge in edges:
                count *= sum(
                    row["source_node_id"] == binding[edge["from"]]
                    and row["target_node_id"] == binding[edge["to"]]
                    and row["type"] == edge["type"]
                    and (
                        edge.get("logical_key") is None
                        or row["logical_key"] == edge["logical_key"]
                    )
                    for row in self.relations
                )
            return count

        pattern = query["match"]
        result = []
        for combination in product(*(candidates(node) for node in pattern["nodes"])):
            self.tick()
            binding = dict(
                zip((node["as"] for node in pattern["nodes"]), combination, strict=True)
            )
            multiplicity = edge_count(binding, pattern.get("edges", []))
            if not multiplicity or not self.predicates(binding, query["where"]):
                continue
            optional = query["optional_match"]
            if not optional:
                self.tick(multiplicity)
                result.extend([binding] * multiplicity)
                continue
            clause = optional[0]
            node = clause["nodes"][0]
            matches = []
            for candidate in candidates(node):
                self.tick()
                extended = {**binding, node["as"]: candidate}
                if edge_count(extended, clause["edges"]) and self.predicates(
                    extended, clause["where"]
                ):
                    matches.append(extended)
            matches = matches or [{**binding, node["as"]: None}]
            self.tick(len(matches) * multiplicity)
            result.extend(matches * multiplicity)
        return result

    def validate_fields(self, query: dict[str, Any]) -> None:
        aliases = {node["as"]: node["type"] for node in query["match"]["nodes"]}
        for clause in query["optional_match"]:
            aliases.update({node["as"]: node["type"] for node in clause["nodes"]})
        types = {
            (row["entity_type"], row["field_name"]): row["json_type"]
            for row in self.facts["observed_field"]
        }

        def field_type(reference: str) -> str:
            alias, _, field = reference.partition(".")
            resolved = types.get((aliases[alias], field))
            if resolved is None:
                raise QueryValidationError(f"unknown field {reference}")
            return str(resolved)

        for group in query["group_by"]:
            if field_type(group["field"]) in {"array", "object"}:
                raise QueryValidationError("group keys must be scalar")
        for measure in query["measures"]:
            if measure["op"] == "sum" and field_type(measure["field"]) not in {
                "number",
                "unresolved",
            }:
                raise QueryValidationError("sum requires a numeric field")
        predicates = [
            *query["where"],
            *(
                predicate
                for clause in query["optional_match"]
                for predicate in clause["where"]
            ),
        ]
        for predicate in predicates:
            resolved = field_type(predicate["left"]["field"])
            if predicate["op"] == "exists":
                continue
            values = (
                predicate["right"]["values"]
                if predicate["op"] == "in"
                else [predicate["right"]["value"]]
            )
            if resolved != "unresolved" and any(
                value is not None and json_type(value) != resolved for value in values
            ):
                raise QueryValidationError(
                    "comparison literal does not match field type"
                )
            if predicate["op"] in {"lt", "lte", "gt", "gte"} and resolved not in {
                "number",
                "string",
                "unresolved",
            }:
                raise QueryValidationError(
                    "ordered comparison requires a string or number"
                )

    def aggregate(
        self, query: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
        self.validate_fields(query)
        bindings = self.bindings(query)
        groups: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
        if not query["group_by"]:
            groups["{}"] = ({}, [])
        for binding in bindings:
            key = {}
            for group in query["group_by"]:
                row = self.field(binding, group["field"])
                key[group["as"]] = typed(
                    None if row is None else json.loads(row["value_json"]),
                    present=row is not None,
                )
            serialized = canonical_json(key)
            groups.setdefault(serialized, (key, []))[1].append(binding)
        population = population_hash(query)
        output, membership = [], {}
        for key, members in groups.values():
            self.tick(0)
            measures, coverage = {}, {}
            for measure in query["measures"]:
                selected = self.selected(members, measure)
                name, op = measure["as"], measure["op"]
                if op != "sum":
                    ids = [
                        binding[measure["node"]]
                        for binding in selected
                        if binding[measure["node"]] is not None
                    ]
                    measures[name] = checked_integer(
                        len(set(ids) if op == "count_distinct" else ids)
                    )
                else:
                    seen: set[str] = set()
                    total, skipped = 0, 0
                    owner = measure["field"].partition(".")[0]
                    for binding in selected:
                        identity = binding[owner]
                        if identity is None or (
                            measure["distinct_on"] and identity in seen
                        ):
                            continue
                        seen.add(identity)
                        row = self.field(binding, measure["field"])
                        value = None if row is None else json.loads(row["value_json"])
                        if value is None:
                            skipped += 1
                            continue
                        total += checked_integer(value)
                    measures[name] = checked_integer(total)
                    coverage[name] = {"skipped_null_or_missing": skipped}
            derived = {}
            for ratio in query["derive"]:
                numerator, denominator = (
                    measures[ratio["numerator"]],
                    measures[ratio["denominator"]],
                )
                with localcontext() as context:
                    context.prec = 64
                    decimal = (
                        None
                        if denominator == 0
                        else format(
                            (Decimal(numerator) / Decimal(denominator)).quantize(
                                Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
                            ),
                            "f",
                        )
                    )
                derived[ratio["as"]] = {
                    "numerator": numerator,
                    "denominator": denominator,
                    "decimal": decimal,
                }
            identity = sha256_json({"population_hash": population, "group_key": key})
            output.append(
                {
                    "group_id": identity,
                    "key": key,
                    "measures": measures,
                    "derived": derived,
                    "coverage": coverage,
                }
            )
            membership[identity] = members

        def compare(left: dict[str, Any], right: dict[str, Any]) -> int:
            for order in query["order_by"]:
                name = order["result"]

                def value(row: dict[str, Any], name: str = name) -> Any:
                    if name in row["measures"]:
                        return (0, row["measures"][name])
                    if name in row["derived"]:
                        ratio = row["derived"][name]
                        return (
                            (1, Fraction(0))
                            if not ratio["denominator"]
                            else (0, Fraction(ratio["numerator"], ratio["denominator"]))
                        )
                    key = row["key"][name]
                    val = key.get("value")
                    return (
                        key["kind"],
                        key.get("type", ""),
                        (val.casefold(), val) if isinstance(val, str) else val,
                    )

                def absent_rank(row: dict[str, Any], name: str = name) -> int:
                    if name in row["derived"]:
                        return int(row["derived"][name]["denominator"] == 0)
                    if name in row["key"]:
                        return {"value": 0, "null": 1, "missing": 2}[
                            row["key"][name]["kind"]
                        ]
                    return 0

                left_rank, right_rank = absent_rank(left), absent_rank(right)
                if left_rank != right_rank:
                    return (left_rank > right_rank) - (left_rank < right_rank)
                a, b = value(left), value(right)
                difference = int(a > b) - int(a < b)
                if difference:
                    return difference if order["direction"] == "asc" else -difference
            return int(left["group_id"] > right["group_id"]) - int(
                left["group_id"] < right["group_id"]
            )

        output.sort(key=cmp_to_key(compare))
        self.tick(0)
        start, end = query["offset"], query["offset"] + query["limit"]
        return {
            "query_ir_version": "2",
            "request_hash": sha256_json(query),
            "population_hash": population,
            "semantics": SEMANTICS,
            "groups": output[start:end],
            "total_groups": len(output),
            "truncated": end < len(output),
            "complete_input": True,
        }, membership

    @staticmethod
    def selected(
        bindings: list[dict[str, Any]], measure: dict[str, Any]
    ) -> list[dict[str, Any]]:
        when = measure["when"]
        if not when:
            return bindings
        if when["bound"] is not None:
            return [row for row in bindings if row[when["bound"]] is not None]
        return [row for row in bindings if row[when["unbound"]] is None]

    def inspect(self, document: dict[str, Any]) -> dict[str, Any]:
        if set(document) - {
            "name",
            "source_where",
            "limit",
            "offset",
        } or not isinstance(document.get("name"), str):
            raise QueryValidationError(
                "inspection requires a name and optional source_where/limit/offset"
            )
        declarations = [
            row
            for row in self.facts["ontology_declaration"]
            if row["name"] == document["name"]
        ]
        if len(declarations) != 1:
            raise QueryValidationError("unknown or ambiguous relation declaration")
        declaration = declarations[0]
        definition = {
            "from": {
                "type": declaration["from_entity"],
                "fields": json.loads(declaration["from_fields_json"]),
            },
            "to": {
                "type": declaration["to_entity"],
                "fields": json.loads(declaration["to_fields_json"]),
            },
            "relation": declaration["relation_type"],
        }
        source, target = definition["from"], definition["to"]
        where = document.get("source_where", [])
        parse_query_ir(
            {
                "query_ir_version": "1",
                "return": [{"count": True}],
                "match": {"nodes": [{"type": source["type"], "as": "source"}]},
                "where": where,
            }
        )

        def keys(node_id: str, fields: list[str], paired_types: list[str]) -> list[Any]:
            components = []
            for field, paired_type in zip(fields, paired_types, strict=True):
                row = self.attrs.get((node_id, field))
                value = None if row is None else json.loads(row["value_json"])
                if value is None:
                    return []
                values = value if isinstance(value, list) else [value]
                items = []
                for item in values:
                    if item is None:
                        continue
                    tag = typed(item)
                    if paired_type != "array" and tag["type"] != paired_type:
                        raise QueryValidationError(
                            "join array element has an incompatible type"
                        )
                    items.append(canonical_json(tag))
                if not items:
                    return []
                components.append(sorted(set(items)))
            expanded = []
            for key in product(*components):
                self.tick()
                expanded.append(key)
            return expanded

        def field_types(endpoint: dict[str, Any]) -> list[str]:
            types = {
                (row["entity_type"], row["field_name"]): row["json_type"]
                for row in self.facts["observed_field"]
            }
            return [
                types.get((endpoint["type"], field), "unresolved")
                for field in endpoint["fields"]
            ]

        index: dict[Any, str] = {}
        for node in self.nodes.values():
            if f"{node['namespace']}.{node['type']}" == target["type"]:
                for key in keys(node["id"], target["fields"], field_types(source)):
                    if key in index and index[key] != node["id"]:
                        raise QueryValidationError(
                            "ambiguous_target: multiple targets for a key"
                        )
                    index[key] = node["id"]
        rows, tuple_count = [], 0
        for node in sorted(self.nodes.values(), key=lambda item: item["id"]):
            self.tick()
            if f"{node['namespace']}.{node['type']}" != source[
                "type"
            ] or not self.predicates({"source": node["id"]}, where):
                continue
            source_keys = keys(node["id"], source["fields"], field_types(target))
            tuple_count += len(source_keys)
            targets = sorted({index[key] for key in source_keys if key in index})
            edges = [
                row
                for row in self.facts["relation"]
                if row["source_node_id"] == node["id"]
                and row["logical_key"] == document["name"]
                and row["type"] == definition["relation"]
            ]
            active = {row["target_node_id"] for row in edges if row["active"]}
            if active - set(targets):
                reason = "active_keys_disagree"
            elif not source_keys:
                reason = "missing_or_null_key"
            elif not targets:
                reason = "no_target"
            elif active >= set(targets):
                reason = "linked"
            elif any(
                not row["active"] and row["target_node_id"] in targets for row in edges
            ):
                reason = "inactive_relation"
            else:
                reason = "eligible_not_materialized"
            rows.append(
                {
                    "source_node_id": node["id"],
                    "key_tuples": source_keys,
                    "target_node_ids": targets,
                    "active_target_node_ids": sorted(active),
                    "reason": reason,
                }
            )
        start, limit = document.get("offset", 0), document.get("limit", 100)
        if (
            type(start) is not int
            or start < 0
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise QueryValidationError("invalid inspection pagination")
        return {
            "population_hash": sha256_json(
                {
                    key: value
                    for key, value in document.items()
                    if key not in {"limit", "offset"}
                }
            ),
            "rows": rows[start : start + limit],
            "total_sources": len(rows),
            "total_key_tuples": tuple_count,
            "reasons": {
                reason: sum(row["reason"] == reason for row in rows)
                for reason in sorted({row["reason"] for row in rows})
            },
            "truncated": start + limit < len(rows),
            "complete_input": True,
        }


def validate_analysis(document: dict[str, Any]) -> dict[str, Any]:
    try:
        request = AnalysisRequest.model_validate(document).model_dump(mode="json")
    except ValidationError as exc:
        raise QueryValidationError(str(exc)) from exc
    for member in request["members"]:
        if member["kind"] == "query":
            member["document"] = validate_query(member["document"])
    return request


def execute_analysis(
    facts: dict[str, Any], request: dict[str, Any], *, retain_membership: bool = False
) -> dict[str, Any]:
    evaluator = Evaluator(facts)
    members = {}
    retained: dict[str, Any] = {}
    for member in request["members"]:
        if member["kind"] == "query":
            result, membership = evaluator.aggregate(member["document"])
            if retain_membership:
                retained[member["name"]] = {}
                for group_id, bindings in membership.items():
                    deduplication = {}
                    for measure in member["document"]["measures"]:
                        selected = {
                            id(binding)
                            for binding in evaluator.selected(bindings, measure)
                        }
                        owner = (
                            measure["node"]
                            if measure["op"] != "sum"
                            else measure["field"].partition(".")[0]
                        )
                        indices = []
                        for index, binding in enumerate(bindings):
                            if id(binding) not in selected or binding[owner] is None:
                                continue
                            if measure["op"] == "sum":
                                attribute = evaluator.field(binding, measure["field"])
                                if (
                                    attribute is None
                                    or json.loads(attribute["value_json"]) is None
                                ):
                                    continue
                            indices.append(index)
                        deduplication[measure["as"]] = {
                            "contributing_binding_indices": indices,
                            "node_ids": sorted(
                                {bindings[index][owner] for index in indices}
                            ),
                            "deduplicate_by": owner
                            if measure["op"] == "count_distinct"
                            else measure["distinct_on"],
                        }
                    retained[member["name"]][group_id] = {
                        "bindings": bindings,
                        "measures": deduplication,
                    }
        else:
            result = evaluator.inspect(member["document"])
        members[member["name"]] = {"kind": member["kind"], **result}
    coverage = {}
    for role, reference in request["coverage_scope"].items():
        member = members[reference["member"]]
        if (
            member["kind"] != "query"
            or member["total_groups"] != 1
            or len(member["groups"]) != 1
            or member["groups"][0]["key"]
        ):
            raise QueryValidationError(
                "coverage role requires an unpaginated global query measure"
            )
        try:
            coverage[role] = member["groups"][0]["measures"][reference["measure"]]
        except KeyError as exc:
            raise QueryValidationError(
                "coverage role references an unknown measure"
            ) from exc
    return {
        **({"membership": retained} if retain_membership else {}),
        "members": members,
        "coverage": coverage,
        "population_hash": sha256_json(
            {
                "semantics": SEMANTICS,
                "members": {
                    name: {
                        "kind": member["kind"],
                        "population_hash": member["population_hash"],
                    }
                    for name, member in members.items()
                },
                "coverage_scope": request["coverage_scope"],
            }
        ),
        "complete_input": True,
    }


class DataState(APIModel):
    generation: str = Field(min_length=1, description="Memory lifetime UUID.")
    data_revision: int = Field(
        ge=0, strict=True, description="Monotonic committed fact revision."
    )


class CaptureDocument(APIModel):
    analysis: AnalysisRequest = Field(
        description="Named typed query and inspection members."
    )
    expected_state: DataState = Field(
        description="Exact state returned by the original analysis."
    )
    definition_version: str = Field(
        min_length=1, description="Stable user-defined analytical definition version."
    )


class DrillDocument(APIModel):
    query: dict[str, Any] | None = Field(
        default=None, description="Original v2 query for live detail."
    )
    observation_id: str | None = Field(
        default=None, description="Saved immutable observation ID."
    )
    query_name: str | None = Field(
        default=None, description="Exact saved query member name."
    )
    expected_state: DataState | None = Field(
        default=None, description="Required original live result state on every page."
    )
    group_key: dict[str, Any] = Field(
        description="Exact typed group key from the aggregate."
    )
    measure: str = Field(
        min_length=1, description="Named measure or ratio to reconcile."
    )
    view: Literal[
        "bindings", "counted_entities", "provenance", "numerator", "denominator"
    ] = Field(
        default="counted_entities",
        description="Membership or provenance view; ratios use numerator/denominator.",
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
        strict=True,
        description="Returned detail rows per page.",
    )
    offset: int = Field(default=0, ge=0, strict=True, description="Output row offset.")
    public: bool = Field(
        default=False,
        strict=True,
        description="Apply native public-use freshness and dependency gates.",
    )

    @model_validator(mode="after")
    def live_or_saved(self) -> DrillDocument:
        if (self.query is None) == (self.observation_id is None):
            raise ValueError("provide exactly one live query or observation_id")
        if self.query is not None and (
            self.expected_state is None or self.query_name is not None
        ):
            raise ValueError(
                "live detail requires expected_state and no saved query_name"
            )
        if self.observation_id is not None and (
            self.query_name is None or self.expected_state is not None
        ):
            raise ValueError(
                "saved detail requires query_name and no live expected_state"
            )
        return self


class ReadDocument(APIModel):
    observation_id: str = Field(min_length=1, description="Saved observation ID.")
    fresh_only: bool = Field(
        default=False, strict=True, description="Reject stale or unknown observations."
    )
    public: bool = Field(
        default=False,
        strict=True,
        description="Require verified current public dependencies and captured inputs.",
    )


class InspectionDocument(APIModel):
    name: str = Field(
        min_length=1, description="Exact materialized join declaration name."
    )
    source_where: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=32,
        description="AND predicates using source.field references.",
    )
    expected_state: DataState = Field(
        description="Generation/revision guard on every inspection page."
    )
    limit: int = Field(
        default=100, ge=1, le=1000, strict=True, description="Returned source rows."
    )
    offset: int = Field(
        default=0, ge=0, strict=True, description="Output source row offset."
    )


NATIVE_DOCUMENT_MODELS: dict[str, type[APIModel]] = {
    "analysis_execute": AnalysisRequest,
    "analysis_capture": CaptureDocument,
    "query_drill_down": DrillDocument,
    "analysis_read": ReadDocument,
    "relation_inspect": InspectionDocument,
}


def validate_native_document(
    operation: str, document: dict[str, Any]
) -> dict[str, Any]:
    model = NATIVE_DOCUMENT_MODELS.get(operation)
    if model is None:
        if operation == "data_state" and document:
            raise QueryValidationError("data_state accepts an empty document")
        return document
    try:
        return model.model_validate(document).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
    except ValidationError as exc:
        raise QueryValidationError(str(exc)) from exc
