from __future__ import annotations

from typing import Any

from analytical_memory.canonical import sha256_json


def ontology_document(
    namespace_declarations: list[dict[str, Any]],
    declarations: list[dict[str, Any]],
    fields: list[dict[str, Any]],
    joins: list[dict[str, Any]],
    statistics: dict[str, Any],
) -> dict[str, Any]:
    entities: dict[str, dict[str, Any]] = {}
    for declaration in declarations:
        entities[declaration["entity_type"]] = {
            "type": declaration["entity_type"],
            "description": declaration["description"],
            "privacy": declaration["privacy_class"],
            "declared": True,
            "fields": {},
            "provenance": {
                "fragment_id": declaration["fragment_id"],
                "recorded_at": declaration["recorded_at"],
                "source_id": declaration["source_id"],
            },
        }
    for field in fields:
        entity = entities.setdefault(
            field["entity_type"],
            {
                "type": field["entity_type"],
                "description": None,
                "privacy": "public",
                "declared": False,
                "fields": {},
                "provenance": None,
            },
        )
        entity["fields"][field["field_name"]] = {
            "type": field["json_type"],
            "description": field["description"],
            "privacy": field["privacy_class"],
            "declared": bool(field["declared"]),
            "required": bool(field["required"]),
            "nullable": bool(field["nullable"]),
            "searchable": bool(field["searchable"]),
        }
    ordered_entities: list[dict[str, Any]] = []
    entity_shapes: list[dict[str, Any]] = []
    for entity_type in sorted(entities):
        entity = entities[entity_type]
        entity["fields"] = {
            name: entity["fields"][name] for name in sorted(entity["fields"])
        }
        ordered_entities.append(entity)
        entity_shapes.append(
            {
                "declared": entity["declared"],
                "description": entity["description"],
                "fields": entity["fields"],
                "privacy": entity["privacy"],
                "type": entity["type"],
            }
        )
    relation_shapes = [
        {
            "name": item["name"],
            "description": item["description"],
            "relation": item["relation_type"],
            "from": {
                "type": item["from_entity"],
                "fields": item["from_fields"],
            },
            "to": {"type": item["to_entity"], "fields": item["to_fields"]},
            "enabled": bool(item["enabled"]),
        }
        for item in joins
    ]
    declared_namespaces = {str(item["name"]): item for item in namespace_declarations}
    namespace_names = set(declared_namespaces)
    namespace_names.update(
        str(entity["type"]).rpartition(".")[0] for entity in ordered_entities
    )
    namespaces = []
    namespace_shapes = []
    for name in sorted(namespace_names):
        namespace_declaration = declared_namespaces.get(name)
        namespace_shape = {
            "name": name,
            "description": (
                None
                if namespace_declaration is None
                else namespace_declaration["description"]
            ),
            "declared": namespace_declaration is not None,
        }
        namespace_shapes.append(namespace_shape)
        namespaces.append(
            {
                **namespace_shape,
                "provenance": (
                    None
                    if namespace_declaration is None
                    else {
                        "fragment_id": namespace_declaration["fragment_id"],
                        "recorded_at": namespace_declaration["recorded_at"],
                        "source_id": namespace_declaration["source_id"],
                    }
                ),
            }
        )
    relations = [
        {
            **relation_shape,
            "statistics": {
                "active_edges": int(item["active_edge_count"]),
                "inactive_edges": int(item["inactive_edge_count"]),
            },
            "provenance": {
                "fragment_id": item["fragment_id"],
                "recorded_at": item["recorded_at"],
                "source_id": item["source_id"],
            },
        }
        for relation_shape, item in zip(relation_shapes, joins, strict=True)
    ]
    shape = {
        "ontology_version": "2",
        "namespaces": namespace_shapes,
        "entities": entity_shapes,
        "relations": relation_shapes,
    }
    return {
        "ontology_version": shape["ontology_version"],
        "namespaces": namespaces,
        "entities": ordered_entities,
        "relations": relations,
        "ontology_fingerprint": sha256_json(shape),
        "statistics": statistics,
    }
