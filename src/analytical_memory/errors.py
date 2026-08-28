from __future__ import annotations

from typing import Any, ClassVar


class MemoryErrorBase(Exception):
    """Base class for expected application errors."""

    code: ClassVar[str] = "memory_error"
    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.details = details or {}
        super().__init__(message)

    def envelope(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "details": self.details,
            "message": str(self),
            "retryable": self.retryable,
        }


class BatchValidationError(MemoryErrorBase):
    code = "batch_validation"


class SchemaChangedError(MemoryErrorBase):
    code = "schema_changed"
    retryable = True

    def __init__(self, supplied: str, current: str) -> None:
        self.supplied = supplied
        self.current = current
        super().__init__(
            "the structural contract fingerprint changed",
            details={
                "current": current,
                "refresh_resource": "memory://schema/current",
                "supplied": supplied,
            },
        )


class IdempotencyConflictError(MemoryErrorBase):
    code = "idempotency_conflict"


class StoreNotInitializedError(MemoryErrorBase):
    code = "store_not_initialized"


class RecordNotFoundError(MemoryErrorBase):
    code = "record_not_found"


class RetentionBlockedError(MemoryErrorBase):
    code = "retention_blocked"


class SnapshotError(MemoryErrorBase):
    code = "snapshot_error"


class EmbeddingProviderError(MemoryErrorBase):
    code = "embedding_provider"


class ImportValidationError(MemoryErrorBase):
    code = "import_validation"


class OntologyConflictError(MemoryErrorBase):
    code = "ontology_conflict"


class AmbiguousTargetError(MemoryErrorBase):
    code = "ambiguous_target"


class JoinConflictError(MemoryErrorBase):
    code = "join_conflict"


class QueryValidationError(MemoryErrorBase):
    code = "query_validation"


class ProhibitedContentError(MemoryErrorBase):
    code = "prohibited_content"


class InvalidRequestError(MemoryErrorBase):
    code = "invalid_request"


class InputOutputError(MemoryErrorBase):
    code = "io_error"


class MemoryCatalogError(MemoryErrorBase):
    code = "memory_catalog"


class MemoryNotFoundError(MemoryErrorBase):
    code = "memory_not_found"


class MemoryUnavailableError(MemoryErrorBase):
    code = "memory_unavailable"


class MemoryStateChangedError(MemoryErrorBase):
    code = "memory_state_changed"
    retryable = True


class MemoryLifecycleError(MemoryErrorBase):
    code = "memory_lifecycle"


class TransferError(MemoryErrorBase):
    code = "transfer_error"


def error_code_registry() -> list[dict[str, Any]]:
    classes = MemoryErrorBase.__subclasses__()
    return [
        {"code": error.code, "retryable": error.retryable}
        for error in sorted(classes, key=lambda item: item.code)
    ]
