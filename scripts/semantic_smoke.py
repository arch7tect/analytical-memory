from __future__ import annotations

import tempfile
from pathlib import Path

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.application import MemoryApplication
from analytical_memory.domain import EmbeddingBatch, EmbeddingProviderInfo
from analytical_memory.ports import EmbeddingProvider
from analytical_memory.schema_contract import load_schema

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class SmokeProvider(EmbeddingProvider):
    @property
    def info(self) -> EmbeddingProviderInfo:
        return EmbeddingProviderInfo(
            provider="openai",
            model="text-embedding-3-small",
            dimensions=1536,
            preprocessing_version="unicode-nfc-lines-v1",
            privacy_ceiling="private",
            configured=True,
        )

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        vectors = []
        for text in texts:
            vector = [0.0] * 1536
            vector[0 if text.casefold().startswith("alpha") else 1] = 1.0
            vectors.append(tuple(vector))
        return EmbeddingBatch(
            vectors=tuple(vectors), response_model="text-embedding-3-small"
        )


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="analytical-memory-semantic-") as root:
        workspace = Path(root)
        application = MemoryApplication(
            SqliteMemoryStore(workspace / "memory.db"),
            FileEvidenceStore(workspace / "evidence"),
            load_schema(REPOSITORY_ROOT / "schema" / "current.json"),
            SmokeProvider(),
        )
        application.initialize()
        application.apply(REPOSITORY_ROOT / "examples" / "querying" / "batch.json")
        profile_id = application.embedding_profile_create("description")["profile"][
            "id"
        ]
        rebuilt = application.embedding_rebuild(profile_id)
        result = application.search_semantic(profile_id, "alpha", limit=1)
        if rebuilt["profile"]["status"] != "ready":
            raise RuntimeError("semantic profile did not become ready")
        if result["results"][0]["fact"]["natural_key"] != "record-a":
            raise RuntimeError("semantic search returned the wrong fixture")
        return {
            "indexed_count": rebuilt["coverage"]["indexed_count"],
            "ok": True,
            "top_fact": "record-a",
        }


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2, sort_keys=True))
