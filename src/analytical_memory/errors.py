class MemoryErrorBase(Exception):
    """Base class for expected application errors."""


class BatchValidationError(MemoryErrorBase):
    pass


class SchemaChangedError(MemoryErrorBase):
    def __init__(self, supplied: str, current: str) -> None:
        self.supplied = supplied
        self.current = current
        super().__init__(
            f"schema_changed: supplied={supplied} current={current} "
            "refresh=memory://schema/current"
        )


class IdempotencyConflictError(MemoryErrorBase):
    pass


class StoreNotInitializedError(MemoryErrorBase):
    pass


class RecordNotFoundError(MemoryErrorBase):
    pass
