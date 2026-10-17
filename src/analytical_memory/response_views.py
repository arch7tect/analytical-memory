"""MCP presentation views applied only after query and evidence validation."""

from __future__ import annotations

from typing import Any, Literal

from analytical_memory.api_models import (
    APIModel,
    JsonType,
    QueryEffectiveOrdering,
    QueryIRResponse,
)


class CompactProjection(APIModel):
    field: str
    json_type: JsonType
    record_id: str | None
    value: Any


class CompactQueryRow(APIModel):
    bindings: dict[str, str]
    projections: list[CompactProjection]


class CompactQueryResponse(APIModel):
    response_format: Literal["compact"]
    contract_fingerprint: str
    count: int | None = None
    ontology_fingerprint: str
    ordering: list[QueryEffectiveOrdering]
    rows: list[CompactQueryRow]
    truncated: bool


def compact_query(response: QueryIRResponse) -> CompactQueryResponse:
    result = response.model_dump(mode="json")
    result["response_format"] = "compact"
    result["rows"] = [
        {
            "bindings": row["bindings"],
            "projections": [
                {key: item[key] for key in ("field", "json_type", "record_id", "value")}
                for item in row["projections"]
            ],
        }
        for row in result["rows"]
    ]
    return CompactQueryResponse.model_validate(result)


def compact_drill(result: dict[str, Any]) -> dict[str, Any]:
    # Provenance is an explicit expansion. Binding rows have no attribute payload.
    if result["view"] == "provenance":
        return result
    return {
        **result,
        "response_format": "compact",
        "rows": [
            {
                "node": {
                    key: row["node"][key]
                    for key in ("id", "namespace", "type", "privacy_class")
                },
                "attributes": [
                    {
                        key: attribute[key]
                        for key in (
                            "id",
                            "attribute_name",
                            "json_type",
                            "privacy_class",
                            "value",
                        )
                    }
                    for attribute in row["attributes"]
                ],
            }
            if result["view"] != "bindings"
            else row
            for row in result["rows"]
        ],
    }
