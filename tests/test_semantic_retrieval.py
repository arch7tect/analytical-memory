from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

import httpx
import pytest

from analytical_memory.adapters.openai import OpenAIEmbeddingProvider
from analytical_memory.application import MemoryApplication
from analytical_memory.canonical import sha256_bytes
from analytical_memory.cli import main
from analytical_memory.configuration import (
    build_application,
    environment_embedding_privacy,
)
from analytical_memory.domain import EmbeddingBatch, EmbeddingProviderInfo
from analytical_memory.errors import BatchValidationError
from analytical_memory.ports import EmbeddingProvider
from analytical_memory.vectors import decode_vector, encode_vector, preprocess_text

from .conftest import ApplicationFixture


def _axis(index: int, value: float = 1.0) -> tuple[float, ...]:
    vector = [0.0] * 1536
    vector[index] = value
    return tuple(vector)


class FixtureEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        configured: bool = True,
        privacy_ceiling: str = "private",
        response_model: str = "text-embedding-3-small",
    ) -> None:
        self.configured = configured
        self.privacy_ceiling = privacy_ceiling
        self.response_model = response_model
        self.calls: list[list[str]] = []

    @property
    def info(self) -> EmbeddingProviderInfo:
        return EmbeddingProviderInfo(
            provider="openai",
            model="text-embedding-3-small",
            dimensions=1536,
            preprocessing_version="unicode-nfc-lines-v1",
            privacy_ceiling=self.privacy_ceiling,
            configured=self.configured,
        )

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        self.calls.append(texts)
        vectors = []
        for text in texts:
            folded = text.casefold()
            if folded.startswith("alpha"):
                vectors.append(_axis(0))
            elif folded.startswith("beta"):
                vectors.append(_axis(1))
            else:
                combined = list(_axis(0))
                combined[1] = 1.0
                vectors.append(tuple(combined))
        return EmbeddingBatch(
            vectors=tuple(vectors), response_model=self.response_model
        )


def _semantic_application(
    fixture: ApplicationFixture, provider: EmbeddingProvider
) -> MemoryApplication:
    return MemoryApplication(
        fixture.memory_store,
        fixture.evidence_store,
        fixture.schema,
        embedding_provider=provider,
    )


def test_exact_semantic_search_rebuild_and_filters_are_deterministic(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
) -> None:
    provider = FixtureEmbeddingProvider()
    application = _semantic_application(application_fixture, provider)
    application.initialize()
    application.apply(querying_batch_path)
    profile = application.embedding_profile_create("description")["profile"]

    rebuilt = application.embedding_rebuild(profile["id"])

    assert rebuilt["profile"]["status"] == "ready"
    assert rebuilt["coverage"] == {
        "eligible_count": 2,
        "indexed_count": 2,
        "complete": True,
    }
    alpha = application.search_semantic(profile["id"], "alpha", limit=2)
    assert [item["fact"]["natural_key"] for item in alpha["results"]] == [
        "record-a",
        "record-b",
    ]
    assert alpha["results"][0]["score"] > alpha["results"][1]["score"]
    filtered = application.search_semantic(profile["id"], "alpha", namespace="missing")
    assert filtered["results"] == []

    tied = application.search_semantic(profile["id"], "unmapped", limit=2)
    document_ids = [item["document_id"] for item in tied["results"]]
    assert document_ids == sorted(document_ids)


def test_profile_and_input_changes_create_new_embedding_records(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
) -> None:
    provider = FixtureEmbeddingProvider()
    application = _semantic_application(application_fixture, provider)
    application.initialize()
    application.apply(querying_batch_path)
    public = application.embedding_profile_create(
        "description", privacy_ceiling="public"
    )["profile"]
    private = application.embedding_profile_create(
        "description", privacy_ceiling="private"
    )["profile"]
    assert public["id"] != private["id"]
    application.embedding_rebuild(public["id"])
    application.embedding_rebuild(private["id"])

    with sqlite3.connect(application_fixture.database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM embedding_profile").fetchone()[0]
            == 2
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM embedding_record").fetchone()[0]
            == 4
        )
        document_id = str(
            connection.execute(
                "SELECT id FROM search_document ORDER BY id LIMIT 1"
            ).fetchone()[0]
        )
        changed = "Alpha changed input"
        connection.execute(
            "UPDATE search_document SET content = ?, content_hash = ? WHERE id = ?",
            (changed, sha256_bytes(changed.encode()), document_id),
        )
    stale = application.embedding_profile_status(public["id"])
    assert stale["profile"]["status"] == "degraded"
    assert stale["coverage"]["complete"] is False
    application.embedding_rebuild(public["id"])
    with sqlite3.connect(application_fixture.database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM embedding_record WHERE profile_id = ?",
            (public["id"],),
        ).fetchone()[0]
    assert count == 3


@pytest.mark.parametrize("restriction", ("source", "node"))
def test_privacy_policy_blocks_restricted_text_before_provider_call(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
    restriction: str,
) -> None:
    provider = FixtureEmbeddingProvider(privacy_ceiling="private")
    application = _semantic_application(application_fixture, provider)
    application.initialize()
    document = json.loads(querying_batch_path.read_text(encoding="utf-8"))
    if restriction == "source":
        document["source"]["privacy_class"] = "restricted"
    else:
        for node in document["nodes"]:
            node["privacy_class"] = "restricted"
    for node in document["nodes"]:
        for attribute in node.get("attributes", []):
            if attribute["name"] == "description":
                attribute["privacy_class"] = "public"
    querying_batch_path.write_text(json.dumps(document), encoding="utf-8")
    plan = application.plan(querying_batch_path)
    assert {item.privacy_class for item in plan.search_documents} == {"restricted"}
    application.apply(querying_batch_path)
    profile = application.embedding_profile_create(
        "description", privacy_ceiling="private"
    )["profile"]
    application.embedding_rebuild(profile["id"])

    assert provider.calls == []
    with pytest.raises(ValueError, match="exceeds provider policy"):
        application.embedding_profile_create(
            "description", privacy_ceiling="restricted"
        )


@pytest.mark.parametrize("target", ("source", "node", "attribute", "document"))
def test_privacy_class_is_immutable_across_batches(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
    target: str,
) -> None:
    application = _semantic_application(
        application_fixture, FixtureEmbeddingProvider(privacy_ceiling="restricted")
    )
    application.initialize()
    application.apply(querying_batch_path)

    document = json.loads(querying_batch_path.read_text(encoding="utf-8"))
    document["idempotency_key"] = f"querying-privacy-changed-{target}"
    if target == "source":
        document["source"]["privacy_class"] = "restricted"
    elif target == "node":
        document["nodes"][0]["privacy_class"] = "restricted"
        document["nodes"][0]["attributes"] = []
    elif target == "attribute":
        document["nodes"][0]["attributes"][0]["privacy_class"] = "restricted"
    else:
        document["source"]["natural_key"] = "different-restricted-source"
        document["source"]["privacy_class"] = "restricted"
    querying_batch_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BatchValidationError, match="privacy_class is immutable"):
        application.apply(querying_batch_path)
    with sqlite3.connect(application_fixture.database) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM ingestion_batch").fetchone()[0]
            == 1
        )
        assert connection.execute(
            "SELECT DISTINCT privacy_class FROM search_document"
        ).fetchall() == [("public",)]


def test_missing_or_mismatched_provider_degrades_only_semantic_retrieval(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
) -> None:
    provider = FixtureEmbeddingProvider(configured=False)
    application = _semantic_application(application_fixture, provider)
    application.initialize()
    application.apply(querying_batch_path)
    facts_before = application.current_facts()
    profile = application.embedding_profile_create("description")["profile"]

    rebuilt = application.embedding_rebuild(profile["id"])
    search = application.search_semantic(profile["id"], "alpha")

    assert rebuilt["profile"]["status"] == "degraded"
    assert search["status"] == "degraded"
    assert search["results"] == []
    assert application.current_facts() == facts_before

    mismatched = FixtureEmbeddingProvider(response_model="changed-model")
    changed_application = _semantic_application(application_fixture, mismatched)
    changed = changed_application.embedding_rebuild(profile["id"])
    assert changed["profile"]["status"] == "degraded"
    assert changed["coverage"]["indexed_count"] == 0


def test_reset_and_rebuild_preserve_canonical_facts(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
) -> None:
    application = _semantic_application(application_fixture, FixtureEmbeddingProvider())
    application.initialize()
    application.apply(querying_batch_path)
    profile_id = application.embedding_profile_create("description")["profile"]["id"]
    application.embedding_rebuild(profile_id)
    facts = application.current_facts()

    rebuilt = application.embedding_rebuild(profile_id, reset=True)

    assert rebuilt["coverage"]["indexed_count"] == 2
    assert application.current_facts() == facts


def test_openai_adapter_uses_fixed_contract_without_exposing_key() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["Authorization"]
        seen["payload"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": list(_axis(0)), "index": 0}],
                "model": "text-embedding-3-small",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAIEmbeddingProvider("secret-value", client=client)

    batch = provider.embed(["hello"])

    assert batch.response_model == "text-embedding-3-small"
    assert len(batch.vectors[0]) == 1536
    assert seen["authorization"] == "Bearer secret-value"
    assert "secret-value" not in repr(provider.info)


def test_vector_encoding_is_finite_normalized_little_endian_float32() -> None:
    encoded = encode_vector([3.0, 4.0], 2)

    assert encoded == struct.pack("<2f", 0.6, 0.8)
    assert decode_vector(encoded, 2) == pytest.approx((0.6, 0.8))
    assert preprocess_text(" e\u0301\r\n") == "é"
    with pytest.raises(ValueError, match="non-finite"):
        encode_vector([float("nan")], 1)


def test_cli_rebuild_degrades_without_api_key(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fixture = application_fixture
    shared = [
        "--database",
        str(fixture.database),
        "--evidence-root",
        str(fixture.evidence_store.root),
    ]
    assert main([*shared, "init"]) == 0
    capsys.readouterr()
    assert main([*shared, "ingest", "apply", str(querying_batch_path)]) == 0
    capsys.readouterr()
    assert main([*shared, "embedding", "create-profile", "description"]) == 0
    created = capsys.readouterr()
    profile_id = json.loads(created.out)["profile"]["id"]
    assert main([*shared, "embedding", "rebuild", profile_id]) == 0
    rebuilt = json.loads(capsys.readouterr().out)
    assert rebuilt["profile"]["status"] == "degraded"
    assert main([*shared, "search", "alpha", "--semantic-profile", profile_id]) == 0
    search = json.loads(capsys.readouterr().out)
    assert search["status"] == "degraded"
    assert search["results"] == []


def test_invalid_embedding_privacy_configuration_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANALYTICAL_MEMORY_EMBEDDING_PRIVACY", "publik")

    with pytest.raises(ValueError, match="ANALYTICAL_MEMORY_EMBEDDING_PRIVACY"):
        build_application(
            database=tmp_path / "memory.db",
            evidence_root=tmp_path / "evidence",
        )


def test_default_embedding_privacy_allows_all_non_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANALYTICAL_MEMORY_EMBEDDING_PRIVACY", raising=False)

    assert environment_embedding_privacy() == "restricted"
    assert OpenAIEmbeddingProvider(None).info.privacy_ceiling == "restricted"


def test_reset_without_key_preserves_existing_vectors(
    application_fixture: ApplicationFixture,
    querying_batch_path: Path,
) -> None:
    application = _semantic_application(application_fixture, FixtureEmbeddingProvider())
    application.initialize()
    application.apply(querying_batch_path)
    profile_id = application.embedding_profile_create("description")["profile"]["id"]
    application.embedding_rebuild(profile_id)
    unavailable = _semantic_application(
        application_fixture, FixtureEmbeddingProvider(configured=False)
    )

    result = unavailable.embedding_rebuild(profile_id, reset=True)

    assert result["profile"]["status"] == "degraded"
    assert result["coverage"]["indexed_count"] == 2
