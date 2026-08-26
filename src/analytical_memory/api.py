from __future__ import annotations

from pathlib import Path

from analytical_memory.api_models import (
    ApplyResponse,
    CurrentFactsResponse,
    ExplanationResponse,
    PreviewResponse,
)
from analytical_memory.application import MemoryApplication


class MemoryAPI:
    def __init__(self, application: MemoryApplication) -> None:
        self.application = application

    def ingestion_preview(self, batch_path: str | Path) -> PreviewResponse:
        return PreviewResponse.model_validate(
            self.application.preview(Path(batch_path))
        )

    def ingestion_apply(self, batch_path: str | Path) -> ApplyResponse:
        return ApplyResponse.model_validate(self.application.apply(Path(batch_path)))

    def query_current_facts(self) -> CurrentFactsResponse:
        return CurrentFactsResponse.model_validate(self.application.current_facts())

    def explain(self, attribute_id: str) -> ExplanationResponse:
        return ExplanationResponse.model_validate(
            self.application.explain(attribute_id)
        )
