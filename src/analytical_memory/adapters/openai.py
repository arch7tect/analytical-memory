from __future__ import annotations

from typing import Any

import httpx

from analytical_memory.domain import EmbeddingBatch, EmbeddingProviderInfo
from analytical_memory.errors import EmbeddingProviderError
from analytical_memory.ports import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = "https://api.openai.com/v1",
        privacy_ceiling: str = "public",
        client: httpx.Client | None = None,
    ) -> None:
        if privacy_ceiling != "public":
            raise ValueError("external embeddings require public privacy")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._privacy_ceiling = privacy_ceiling
        self._client = client

    @property
    def info(self) -> EmbeddingProviderInfo:
        return EmbeddingProviderInfo(
            provider="openai",
            model="text-embedding-3-small",
            dimensions=1536,
            preprocessing_version="unicode-nfc-lines-v1",
            privacy_ceiling=self._privacy_ceiling,
            configured=bool(self._api_key),
        )

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        if not self._api_key:
            raise EmbeddingProviderError("OPENAI_API_KEY is not configured")
        payload = {
            "dimensions": self.info.dimensions,
            "encoding_format": "float",
            "input": texts,
            "model": self.info.model,
        }
        try:
            if self._client is None:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{self._base_url}/embeddings",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json=payload,
                    )
            else:
                response = self._client.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
            response.raise_for_status()
            body: Any = response.json()
            data = sorted(body["data"], key=lambda item: int(item["index"]))
            if [int(item["index"]) for item in data] != list(range(len(texts))):
                raise ValueError("embedding response indices are invalid")
            vectors = tuple(
                tuple(float(value) for value in item["embedding"]) for item in data
            )
            response_model = str(body["model"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise EmbeddingProviderError("embedding API request failed") from exc
        if len(vectors) != len(texts):
            raise EmbeddingProviderError("embedding API returned an unexpected count")
        return EmbeddingBatch(vectors=vectors, response_model=response_model)
