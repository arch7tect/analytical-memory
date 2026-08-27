from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters
from mcp.types import TextContent, TextResourceContents

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.api import MemoryAPI
from analytical_memory.application import MemoryApplication
from analytical_memory.canonical import canonical_json, sha256_json
from analytical_memory.cli import main
from analytical_memory.errors import (
    MemoryCatalogError,
    MemoryErrorBase,
    MemoryNotFoundError,
)
from analytical_memory.mcp_operations import OPERATION_DEFINITIONS
from analytical_memory.memories import MemoryRouter
from analytical_memory.schema_contract import load_schema
from scripts.plugin_runtime import _configure_environment


def _application(database: Path, evidence_root: Path) -> MemoryApplication:
    return MemoryApplication(
        SqliteMemoryStore(database), FileEvidenceStore(evidence_root), load_schema()
    )


def _router(tmp_path: Path) -> MemoryRouter:
    application = _application(tmp_path / "default.db", tmp_path / "default-evidence")
    application.initialize()
    return MemoryRouter(application, tmp_path / "memories.json")


def _tool_json(result: Any) -> dict[str, Any]:
    assert result.is_error is False
    assert isinstance(result.content[0], TextContent)
    start = result.content[0].text.index("{")
    value = json.loads(result.content[0].text[start:])
    assert isinstance(value, dict)
    return value


def _missing_property_descriptions(
    schema: dict[str, Any], path: str = "input"
) -> list[str]:
    missing: list[str] = []
    for name, value in schema.get("properties", {}).items():
        if not value.get("description"):
            missing.append(f"{path}.{name}")
        missing.extend(_missing_property_descriptions(value, f"{path}.{name}"))
    for name, value in schema.get("$defs", {}).items():
        missing.extend(_missing_property_descriptions(value, f"{path}.$defs.{name}"))
    for keyword in ("anyOf", "oneOf", "allOf"):
        for index, value in enumerate(schema.get(keyword, [])):
            missing.extend(
                _missing_property_descriptions(value, f"{path}.{keyword}[{index}]")
            )
    items = schema.get("items")
    if isinstance(items, dict):
        missing.extend(_missing_property_descriptions(items, f"{path}.items"))
    return missing


def test_default_is_implicit_and_unknown_never_falls_back(tmp_path: Path) -> None:
    router = _router(tmp_path)

    name, application = router.resolve()

    assert name == "default"
    assert application is router.default_application
    assert not router.catalog_path.exists()
    assert set(router.catalog()["memories"]) == {"default"}
    with pytest.raises(MemoryNotFoundError):
        router.resolve("missing")


def test_plugin_empty_environment_values_use_plugin_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "ANALYTICAL_MEMORY_DATA_ROOT",
        "ANALYTICAL_MEMORY_CATALOG",
        "ANALYTICAL_MEMORY_DB",
        "ANALYTICAL_MEMORY_EVIDENCE_ROOT",
    ):
        monkeypatch.setenv(name, "")

    _configure_environment(tmp_path)

    assert os.environ["ANALYTICAL_MEMORY_DATA_ROOT"] == str(tmp_path)
    assert os.environ["ANALYTICAL_MEMORY_CATALOG"] == str(tmp_path / "memories.json")
    assert os.environ["ANALYTICAL_MEMORY_DB"] == str(tmp_path / "memory.db")
    assert os.environ["ANALYTICAL_MEMORY_EVIDENCE_ROOT"] == str(tmp_path / "evidence")


def test_create_named_sqlite_memory_and_catalog_permissions(tmp_path: Path) -> None:
    router = _router(tmp_path)
    database = tmp_path / "research" / "memory.db"
    evidence = tmp_path / "research" / "evidence"

    configured = router.configure(
        action="create",
        name="research",
        backend="sqlite",
        database=database,
        evidence_root=evidence,
    )
    name, application = router.resolve("research")

    assert configured["memory"] == "research"
    assert name == "research"
    assert application.status()["ready"] is True
    assert database.is_file()
    assert stat.S_IMODE(router.catalog_path.stat().st_mode) == 0o600
    catalog = json.loads(router.catalog_path.read_text(encoding="utf-8"))
    assert catalog["memories"]["research"] == {
        "backend": "sqlite",
        "database": str(database),
        "evidence_root": str(evidence),
    }


def test_attach_is_read_only_and_checks_exact_migrations(tmp_path: Path) -> None:
    router = _router(tmp_path)
    database = tmp_path / "existing" / "memory.db"
    evidence = tmp_path / "existing" / "evidence"
    existing = _application(database, evidence)
    existing.initialize()
    before = database.stat().st_mtime_ns

    router.configure(
        action="attach",
        name="existing",
        backend="sqlite",
        database=database,
        evidence_root=evidence,
    )

    assert database.stat().st_mtime_ns == before
    assert router.resolve("existing")[1].status()["ready"] is True

    incompatible_database = tmp_path / "incompatible.db"
    incompatible_database.write_bytes(b"not a database")
    incompatible_evidence = tmp_path / "incompatible-evidence"
    incompatible_evidence.mkdir()
    with pytest.raises(MemoryErrorBase):
        router.configure(
            action="attach",
            name="incompatible",
            backend="sqlite",
            database=incompatible_database,
            evidence_root=incompatible_evidence,
        )
    assert "incompatible" not in router.catalog()["memories"]


def test_attach_ignores_evidence_availability_but_rejects_tampered_ledger(
    tmp_path: Path,
) -> None:
    router = _router(tmp_path)
    database = tmp_path / "detached" / "memory.db"
    evidence = tmp_path / "detached" / "evidence"
    existing = _application(database, evidence)
    existing.initialize()
    source = tmp_path / "records.jsonl"
    source.write_text('{"id":"one"}\n', encoding="utf-8")
    imported = MemoryAPI(existing).jsonl_import(
        source,
        "notes.Record",
        [{"field": "id", "type": "string"}],
        existing.schema.fingerprint,
    )
    existing.evidence_store.remove(imported.evidence_digest)

    router.configure(
        action="attach",
        name="detached",
        backend="sqlite",
        database=database,
        evidence_root=evidence,
    )
    assert router.resolve("detached")[1].status()["ready"] is True

    tampered_database = tmp_path / "tampered" / "memory.db"
    tampered_evidence = tmp_path / "tampered" / "evidence"
    _application(tampered_database, tampered_evidence).initialize()
    with sqlite3.connect(tampered_database) as connection:
        connection.execute(
            "UPDATE schema_migration SET checksum = 'tampered' WHERE version = 1"
        )
    with pytest.raises(MemoryCatalogError, match="not compatible"):
        router.configure(
            action="attach",
            name="tampered",
            backend="sqlite",
            database=tampered_database,
            evidence_root=tampered_evidence,
        )


def test_failed_attach_does_not_create_target(tmp_path: Path) -> None:
    router = _router(tmp_path)
    database = tmp_path / "absent" / "memory.db"
    evidence = tmp_path / "absent" / "evidence"

    with pytest.raises(MemoryCatalogError):
        router.configure(
            action="attach",
            name="absent",
            backend="sqlite",
            database=database,
            evidence_root=evidence,
        )

    assert not database.exists()
    assert not evidence.exists()


def test_targets_and_evidence_roots_must_be_disjoint(tmp_path: Path) -> None:
    router = _router(tmp_path)
    database = tmp_path / "one.db"
    evidence = tmp_path / "one-evidence"
    router.configure(
        action="create",
        name="one",
        backend="sqlite",
        database=database,
        evidence_root=evidence,
    )

    with pytest.raises(MemoryCatalogError, match="SQLite targets"):
        router.configure(
            action="attach",
            name="two",
            backend="sqlite",
            database=database,
            evidence_root=tmp_path / "two-evidence",
        )
    with pytest.raises(MemoryCatalogError, match="evidence roots"):
        router.configure(
            action="create",
            name="nested",
            backend="sqlite",
            database=tmp_path / "nested.db",
            evidence_root=evidence / "nested",
        )
    with pytest.raises(MemoryCatalogError, match="inside an evidence root"):
        router.configure(
            action="create",
            name="embedded",
            backend="sqlite",
            database=tmp_path / "embedded-evidence" / "memory.db",
            evidence_root=tmp_path / "embedded-evidence",
        )


def test_cache_tracks_catalog_target_and_concurrent_writes_merge(
    tmp_path: Path,
) -> None:
    router = _router(tmp_path)
    first_database = tmp_path / "first.db"
    first_evidence = tmp_path / "first-evidence"
    router.configure(
        action="create",
        name="research",
        backend="sqlite",
        database=first_database,
        evidence_root=first_evidence,
    )
    first_store = router.resolve("research")[1].memory_store
    assert isinstance(first_store, SqliteMemoryStore)
    assert first_store.database == first_database

    second_database = tmp_path / "second.db"
    second_evidence = tmp_path / "second-evidence"
    _application(second_database, second_evidence).initialize()
    catalog = json.loads(router.catalog_path.read_text(encoding="utf-8"))
    catalog["memories"]["research"] = {
        "backend": "sqlite",
        "database": str(second_database),
        "evidence_root": str(second_evidence),
    }
    router.catalog_path.write_text(canonical_json(catalog) + "\n", encoding="utf-8")
    second_store = router.resolve("research")[1].memory_store
    assert isinstance(second_store, SqliteMemoryStore)
    assert second_store.database == second_database

    shared_catalog = tmp_path / "concurrent" / "memories.json"
    default = router.default_application

    def configure(name: str) -> None:
        MemoryRouter(default, shared_catalog).configure(
            action="create",
            name=name,
            backend="sqlite",
            database=tmp_path / f"{name}.db",
            evidence_root=tmp_path / f"{name}-evidence",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(configure, ("alpha", "beta")))
    memories = MemoryRouter(default, shared_catalog).catalog()["memories"]
    assert set(memories) == {"default", "alpha", "beta"}


def test_postgres_catalog_references_only_prefixed_environment_name(
    tmp_path: Path,
) -> None:
    router = _router(tmp_path)

    with pytest.raises(MemoryCatalogError, match="connection_env"):
        router.configure(
            action="attach",
            name="remote",
            backend="postgresql",
            connection_env="DATABASE_URL",
            postgres_schema="memory",
            evidence_root=tmp_path / "remote-evidence",
        )


def test_cli_catalog_selection_and_capability_fingerprint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shared = [
        "--backend",
        "sqlite",
        "--database",
        str(tmp_path / "default.db"),
        "--evidence-root",
        str(tmp_path / "default-evidence"),
        "--catalog",
        str(tmp_path / "memories.json"),
    ]
    assert main([*shared, "init"]) == 0
    capsys.readouterr()
    assert main([*shared, "capabilities"]) == 0
    capabilities = json.loads(capsys.readouterr().out)
    runtime_fingerprint = capabilities.pop("runtime_fingerprint")
    assert runtime_fingerprint == sha256_json(capabilities)
    assert main([*shared, "status"]) == 0
    status_document = json.loads(capsys.readouterr().out)
    assert status_document["runtime_fingerprint"] == runtime_fingerprint

    assert main([*shared, "memories", "list"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert set(catalog["memories"]) == {"default"}

    assert main([*shared, "--memory", "missing", "status"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["code"] == "memory_not_found"
    assert error["details"]["memory"] == "missing"


def test_postgres_create_and_read_only_attach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = os.environ.get("ANALYTICAL_MEMORY_TEST_POSTGRES_URL")
    if dsn is None:
        pytest.skip("ANALYTICAL_MEMORY_TEST_POSTGRES_URL is not configured")
    import psycopg
    from psycopg import sql

    from analytical_memory.adapters.postgresql import PostgresMemoryStore

    connection_env = "ANALYTICAL_MEMORY_TEST_NAMED_POSTGRES_URL"
    monkeypatch.setenv(connection_env, dsn)
    created_schema = f"named_{uuid.uuid4().hex}"
    attached_schema = f"attached_{uuid.uuid4().hex}"
    router = _router(tmp_path)
    attached = MemoryApplication(
        PostgresMemoryStore(dsn, schema=attached_schema),
        FileEvidenceStore(tmp_path / "attached-evidence"),
        load_schema(),
    )
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(attached_schema))
        )
    try:
        attached.initialize()
        router.configure(
            action="create",
            name="remote",
            backend="postgresql",
            connection_env=connection_env,
            postgres_schema=created_schema,
            evidence_root=tmp_path / "remote-evidence",
        )
        router.configure(
            action="attach",
            name="attached",
            backend="postgresql",
            connection_env=connection_env,
            postgres_schema=attached_schema,
            evidence_root=tmp_path / "attached-evidence",
        )

        assert router.resolve("remote")[1].status()["ready"] is True
        assert router.resolve("attached")[1].status()["ready"] is True
        catalog_text = router.catalog_path.read_text(encoding="utf-8")
        assert connection_env in catalog_text
        assert dsn not in catalog_text
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            for schema in (created_schema, attached_schema):
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema)
                    )
                )


@pytest.mark.anyio
async def test_mcp_configures_and_routes_named_memory(tmp_path: Path) -> None:
    environment = {
        **os.environ,
        "ANALYTICAL_MEMORY_BACKEND": "sqlite",
        "ANALYTICAL_MEMORY_DB": str(tmp_path / "default.db"),
        "ANALYTICAL_MEMORY_EVIDENCE_ROOT": str(tmp_path / "default-evidence"),
        "ANALYTICAL_MEMORY_CATALOG": str(tmp_path / "memories.json"),
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "analytical_memory.mcp_server"],
        env=environment,
    )
    async with Client(parameters) as client:
        resources = (await client.list_resources()).resources
        resource_templates = (await client.list_resource_templates()).resource_templates
        tools = (await client.list_tools()).tools
        resource_uris = {str(resource.uri) for resource in resources}
        assert "memory://guide" in resource_uris
        assert all(resource.description for resource in resources)
        assert all(template.description for template in resource_templates)
        assert {template.uri_template for template in resource_templates} == {
            "memory://operations/{operation}",
            "memory://schema/ontology/{namespace}",
            "memory://memories/{memory}/capabilities/current",
            "memory://memories/{memory}/schema/ontology/current",
            "memory://memories/{memory}/schema/ontology/{namespace}",
        }
        assert all(tool.description for tool in tools)
        assert {
            tool.name: missing_descriptions
            for tool in tools
            if (
                missing_descriptions := _missing_property_descriptions(
                    tool.input_schema
                )
            )
        } == {}
        assert {
            tool.name: missing_descriptions
            for tool in tools
            if tool.output_schema is None
            or (
                missing_descriptions := _missing_property_descriptions(
                    tool.output_schema
                )
            )
        } == {}
        for resource in resources:
            result = await client.read_resource(str(resource.uri))
            assert isinstance(result.contents[0], TextResourceContents)
            assert isinstance(json.loads(result.contents[0].text), dict)
        default_namespace = await client.read_resource(
            "memory://schema/ontology/unused"
        )
        assert isinstance(default_namespace.contents[0], TextResourceContents)
        assert isinstance(json.loads(default_namespace.contents[0].text), dict)

        guide_resource = await client.read_resource("memory://guide")
        assert isinstance(guide_resource.contents[0], TextResourceContents)
        guide = json.loads(guide_resource.contents[0].text)
        assert set(guide) == {
            "errors",
            "guide_version",
            "operations",
            "purpose",
            "results",
            "safety",
            "selection",
            "workflow",
        }
        assert [step["step"] for step in guide["workflow"]] == [1, 2, 3, 4, 5, 6]

        schema_resource = await client.read_resource("memory://schema/current")
        assert isinstance(schema_resource.contents[0], TextResourceContents)
        schema_document = json.loads(schema_resource.contents[0].text)
        assert "memory" not in schema_document
        schema_copy = tmp_path / "schema.json"
        schema_copy.write_text(canonical_json(schema_document), encoding="utf-8")
        assert (
            load_schema(schema_copy).fingerprint
            == schema_document["schema_fingerprint"]
        )
        default_capabilities = await client.read_resource(
            "memory://capabilities/current"
        )
        assert isinstance(default_capabilities.contents[0], TextResourceContents)
        default_capability_document = json.loads(default_capabilities.contents[0].text)
        default_runtime_fingerprint = default_capability_document.pop(
            "runtime_fingerprint"
        )
        assert default_runtime_fingerprint == sha256_json(default_capability_document)
        assert default_capability_document["capabilities_document_version"] == "4"
        assert set(default_capability_document["discovery"].values()) <= resource_uris
        assert all(
            operation.get("description")
            for operation in default_capability_document["operations"].values()
        )
        operation_index = await client.read_resource("memory://operations")
        assert isinstance(operation_index.contents[0], TextResourceContents)
        operation_index_document = json.loads(operation_index.contents[0].text)
        serialized_operation_index = json.dumps(
            operation_index_document, separators=(",", ":")
        )
        assert len(serialized_operation_index) <= 10_000
        indexed_operations = {
            item["operation"]: item for item in operation_index_document["operations"]
        }
        assert set(indexed_operations) == {
            definition.operation for definition in OPERATION_DEFINITIONS
        }
        tool_by_name = {tool.name: tool for tool in tools}
        operation_spec_sizes: list[int] = []
        for definition in OPERATION_DEFINITIONS:
            operation_resource = await client.read_resource(definition.spec_uri)
            assert isinstance(operation_resource.contents[0], TextResourceContents)
            operation_spec_sizes.append(len(operation_resource.contents[0].text))
            operation_document = json.loads(operation_resource.contents[0].text)
            assert operation_document["mcp_tool"] == definition.mcp_tool
            example_call = operation_document["example"]["call"]
            if definition.action is None:
                assert operation_document["call_style"] == "direct"
                assert "action" not in operation_document
                definition.request_model.model_validate(example_call)
                published_tool = tool_by_name[definition.mcp_tool]
                assert set(published_tool.input_schema["properties"]) == set(
                    operation_document["input_schema"]["properties"]
                )
                assert set(published_tool.input_schema.get("required", [])) == set(
                    operation_document["input_schema"].get("required", [])
                )
                assert published_tool.output_schema is not None
                assert set(published_tool.output_schema["properties"]) == set(
                    operation_document["output_schema"]["properties"]
                )
                assert operation_document["output_location"] == "tool_result"
            else:
                assert operation_document["call_style"] == "manager"
                assert operation_document["action"] == definition.action
                assert example_call["action"] == definition.action
                definition.request_model.model_validate(example_call["payload"])
                assert operation_document["output_location"] == "result"
            assert operation_document["input_schema"] == (
                definition.request_model.model_json_schema(by_alias=True)
            )
            assert operation_document["input_schema"]["properties"]
            assert operation_document["output_schema"]["properties"]
            assert (
                _missing_property_descriptions(operation_document["input_schema"]) == []
            )
            assert (
                _missing_property_descriptions(operation_document["output_schema"])
                == []
            )
        assert max(operation_spec_sizes) <= 15_000

        serialized_tools = json.dumps(
            [
                tool.model_dump(mode="json", by_alias=True, exclude_none=False)
                for tool in tools
            ],
            separators=(",", ":"),
        )
        assert len(tools) == 11
        assert len(serialized_tools) <= 25_000
        callable_capabilities = {
            name: operation
            for name, operation in default_capability_document["operations"].items()
            if "mcp_tool" in operation
        }
        assert set(callable_capabilities) == set(indexed_operations)
        assert {
            operation["mcp_tool"] for operation in callable_capabilities.values()
        } == {tool.name for tool in tools}

        configured = await client.call_tool(
            "memory_configure",
            {
                "action": "create",
                "name": "research",
                "backend": "sqlite",
                "database": str(tmp_path / "research.db"),
                "evidence_root": str(tmp_path / "research-evidence"),
            },
        )
        assert _tool_json(configured)["memory"] == "research"
        capabilities = await client.read_resource(
            "memory://memories/research/capabilities/current"
        )
        assert isinstance(capabilities.contents[0], TextResourceContents)
        capability_document = json.loads(capabilities.contents[0].text)
        assert capability_document["memory"] == "research"
        runtime_fingerprint = capability_document.pop("runtime_fingerprint")
        assert runtime_fingerprint == sha256_json(capability_document)
        ontology = await client.read_resource(
            "memory://memories/research/schema/ontology/current"
        )
        assert isinstance(ontology.contents[0], TextResourceContents)
        ontology_document = json.loads(ontology.contents[0].text)
        fingerprint = ontology_document["contract_fingerprint"]
        declared = await client.call_tool(
            "memory_ontology_manage",
            {
                "action": "declare_namespace",
                "payload": {
                    "namespace": "notes",
                    "description": "Research notes.",
                    "contract_fingerprint": fingerprint,
                },
                "memory": "research",
            },
        )
        declared_document = _tool_json(declared)
        assert declared_document["memory"] == "research"
        assert declared_document["action"] == "declare_namespace"
        declared_namespaces = declared_document["result"]["document"]["namespaces"]
        assert declared_namespaces[0]["name"] == "notes"
        refreshed = await client.read_resource(
            "memory://memories/research/schema/ontology/current"
        )
        assert isinstance(refreshed.contents[0], TextResourceContents)
        refreshed_document = json.loads(refreshed.contents[0].text)
        assert refreshed_document["document"]["namespaces"][0]["name"] == "notes"
        named_namespace = await client.read_resource(
            "memory://memories/research/schema/ontology/notes"
        )
        assert isinstance(named_namespace.contents[0], TextResourceContents)
        named_namespace_document = json.loads(named_namespace.contents[0].text)
        assert named_namespace_document["document"]["namespaces"][0]["name"] == "notes"

        missing = await client.call_tool(
            "memory_search_manage",
            {
                "action": "text",
                "payload": {"query": "anything"},
                "memory": "missing",
            },
        )
        assert missing.is_error is True
        assert isinstance(missing.content[0], TextContent)
        error_text = missing.content[0].text
        error = json.loads(error_text[error_text.index("{") :])
        assert error["code"] == "memory_not_found"
        assert error["details"]["memory"] == "missing"
        assert error["details"]["mcp_tool"] == "memory_search_manage"
        assert error["details"]["action"] == "text"
        assert error["details"]["spec"] == "memory://operations/search_text"

        invalid = await client.call_tool(
            "memory_ontology_manage",
            {
                "action": "declare_namespace",
                "payload": {"namespace": "missing-description"},
                "memory": "research",
            },
        )
        assert invalid.is_error is True
        assert isinstance(invalid.content[0], TextContent)
        invalid_text = invalid.content[0].text
        invalid_error = json.loads(invalid_text[invalid_text.index("{") :])
        assert invalid_error["code"] == "invalid_request"
        assert invalid_error["details"]["action"] == "declare_namespace"
        assert invalid_error["details"]["mcp_tool"] == "memory_ontology_manage"
        assert invalid_error["details"]["memory"] == "research"
        assert invalid_error["details"]["errors"]
        assert invalid_error["details"]["spec"] == (
            "memory://operations/namespace_declaration"
        )

        missing_resource = await client.read_resource(
            "memory://memories/missing/capabilities/current"
        )
        assert isinstance(missing_resource.contents[0], TextResourceContents)
        resource_error = json.loads(missing_resource.contents[0].text)
        assert resource_error["code"] == "memory_not_found"

        (tmp_path / "memories.json").write_text("{", encoding="utf-8")
        corrupt_catalog = await client.read_resource("memory://catalog")
        assert isinstance(corrupt_catalog.contents[0], TextResourceContents)
        catalog_error = json.loads(corrupt_catalog.contents[0].text)
        assert catalog_error["code"] == "memory_catalog"
