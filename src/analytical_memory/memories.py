from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from analytical_memory.adapters.filesystem import FileEvidenceStore
from analytical_memory.adapters.sqlite import SqliteMemoryStore
from analytical_memory.application import MemoryApplication
from analytical_memory.canonical import canonical_json, sha256_json, strict_json_loads
from analytical_memory.configuration import build_application
from analytical_memory.errors import (
    MemoryCatalogError,
    MemoryLifecycleError,
    MemoryNotFoundError,
    MemoryStateChangedError,
    MemoryUnavailableError,
)
from analytical_memory.mcp_operations import MCP_ROUTES

MemoryBackend = Literal["sqlite", "postgresql"]

_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_CONNECTION_ENV = re.compile(r"^ANALYTICAL_MEMORY_[A-Z][A-Z0-9_]*_POSTGRES_URL$")
_ENTRY_KEYS = {
    "sqlite": frozenset({"backend", "database", "evidence_root"}),
    "postgresql": frozenset({"backend", "connection_env", "schema", "evidence_root"}),
}

_OPERATION_DESCRIPTIONS = {
    "analytical_attribute_write": (
        "Write one current analytical Node attribute with run provenance."
    ),
    "analytical_metric_write": (
        "Append one immutable analytical metric observation with exact scope."
    ),
    "delete_node": (
        "Delete one current Node and cascade current graph/search projections."
    ),
    "embedding_rebuild": "Create or rebuild stored embeddings through the CLI.",
    "embedding_status": "Inspect embedding profile coverage and provider readiness.",
    "entity_declaration": (
        "Declare optional entity descriptions, privacy, and field validation."
    ),
    "evidence_audit": (
        "Boundedly verify evidence, report orphans, and append check history."
    ),
    "evidence_read": "Read one bounded evidence byte range as base64.",
    "evidence_status": "Inspect evidence availability, privacy, and verification.",
    "evidence_verify": "Verify one evidence object and append check history.",
    "explain_attribute": "Resolve one current attribute to direct provenance.",
    "explain_metric": "Resolve one metric observation to run and provenance.",
    "explain_relation": "Resolve one current relation to direct provenance.",
    "join_materialize": (
        "Explicitly create directed relations by exact typed field equality."
    ),
    "jsonl_import": "Stream and atomically patch/upsert one JSONL entity dataset.",
    "memory_configure": "Create or attach one named memory target.",
    "memory_lifecycle": (
        "Wipe a selected memory or delete a named memory with an exact state guard."
    ),
    "namespace_declaration": "Declare a human-readable namespace description.",
    "ontology": "Discover current entity, field, relation, and description shape.",
    "query_current_metric": "Select the deterministic metric for an exact scope.",
    "query_execute": "Execute a bounded read-only Query IR document.",
    "relation_deactivate": (
        "Correct current graph state by deactivating one relation."
    ),
    "retention": "Report, plan, release, or retire evidence through the CLI.",
    "sanitized_export": "Export current public data without raw evidence bytes.",
    "search_semantic": "Rank public facts by exact local vector similarity.",
    "search_text": "Full-text search current public searchable string attributes.",
    "snapshot": "Create, verify, or restore a complete local snapshot.",
    "transfer": "Export or import canonical records across supported backends.",
    "traverse_relations": "Traverse bounded active relation paths from one Node.",
}


def contextual_capabilities(
    application: MemoryApplication, memory: str
) -> dict[str, Any]:
    result = application.capabilities()
    result.pop("runtime_fingerprint")
    result["capabilities_document_version"] = "5"
    result["memory"] = memory
    result["operations"] = {
        **result["operations"],
        "memory_configure": {
            "enabled": True,
            "interfaces": ["cli", "mcp"],
            "mutating": True,
        },
        "memory_lifecycle": {
            "enabled": True,
            "interfaces": ["cli", "mcp"],
            "mutating": True,
        },
    }
    for name, operation in result["operations"].items():
        operation["description"] = _OPERATION_DESCRIPTIONS[name]
        operation.pop("mcp_tool", None)
        route = MCP_ROUTES.get(name)
        if route is not None:
            operation.update(route)
    result["discovery"] = {
        "agent_guide": "memory://guide",
        "catalog": "memory://catalog",
        "structural_schema": "memory://schema/current",
        "query_ir": "memory://schema/query-ir/current",
        "capabilities": (
            "memory://capabilities/current"
            if memory == "default"
            else f"memory://memories/{memory}/capabilities/current"
        ),
        "ontology": (
            "memory://schema/ontology/current"
            if memory == "default"
            else f"memory://memories/{memory}/schema/ontology/current"
        ),
        "operations": "memory://operations",
    }
    result["runtime_fingerprint"] = sha256_json(result)
    return result


@dataclass(frozen=True, slots=True)
class MemoryTarget:
    name: str
    backend: MemoryBackend
    evidence_root: Path
    database: Path | None = None
    connection_env: str | None = None
    postgres_schema: str | None = None
    connection_value: str | None = field(default=None, repr=False)

    def document(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "backend": self.backend,
            "evidence_root": str(self.evidence_root),
        }
        if self.backend == "sqlite":
            result["database"] = str(self.database)
        else:
            result["connection_env"] = self.connection_env
            result["schema"] = self.postgres_schema
        return result


def _resolved_path(value: str | Path, field: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise MemoryCatalogError(f"{field} must be an absolute path")
    return path.resolve(strict=False)


def _validate_name(name: str) -> str:
    if name == "default":
        raise MemoryCatalogError("default is reserved and cannot be configured")
    if not _NAME.fullmatch(name):
        raise MemoryCatalogError(
            "memory name must start with a lowercase letter and contain only "
            "lowercase letters, digits, underscores, or hyphens"
        )
    return name


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


class MemoryRouter:
    def __init__(
        self,
        default_application: MemoryApplication,
        catalog_path: Path,
        *,
        cache_size: int = 16,
    ) -> None:
        self.default_application = default_application
        self.catalog_path = catalog_path.expanduser().resolve(strict=False)
        self.cache_size = max(1, cache_size)
        self._cache: OrderedDict[str, MemoryApplication] = OrderedDict()

    def _default_target(self) -> MemoryTarget:
        evidence_store = self.default_application.evidence_store
        if not isinstance(evidence_store, FileEvidenceStore):
            raise MemoryCatalogError("default evidence store is not file-backed")
        store = self.default_application.memory_store
        if isinstance(store, SqliteMemoryStore):
            return MemoryTarget(
                "default",
                "sqlite",
                evidence_store.root.expanduser().resolve(strict=False),
                database=store.database.expanduser().resolve(strict=False),
            )
        from analytical_memory.adapters.postgresql import PostgresMemoryStore

        if isinstance(store, PostgresMemoryStore):
            return MemoryTarget(
                "default",
                "postgresql",
                evidence_store.root.expanduser().resolve(strict=False),
                connection_env="ANALYTICAL_MEMORY_POSTGRES_URL",
                postgres_schema=store.schema,
                connection_value=store.dsn,
            )
        raise MemoryCatalogError("default memory backend is unsupported")

    def _parse_target(self, name: str, raw: Any) -> MemoryTarget:
        if not isinstance(raw, dict):
            raise MemoryCatalogError(f"catalog entry {name!r} must be an object")
        backend = raw.get("backend")
        if backend not in _ENTRY_KEYS:
            raise MemoryCatalogError(f"catalog entry {name!r} has invalid backend")
        if set(raw) != _ENTRY_KEYS[backend]:
            raise MemoryCatalogError(f"catalog entry {name!r} has invalid fields")
        evidence_root = _resolved_path(raw["evidence_root"], "evidence_root")
        if backend == "sqlite":
            return MemoryTarget(
                name,
                "sqlite",
                evidence_root,
                database=_resolved_path(raw["database"], "database"),
            )
        connection_env = raw["connection_env"]
        schema = raw["schema"]
        if not isinstance(connection_env, str) or not _CONNECTION_ENV.fullmatch(
            connection_env
        ):
            raise MemoryCatalogError(
                f"catalog entry {name!r} has invalid connection_env"
            )
        if not isinstance(schema, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]{0,62}", schema
        ):
            raise MemoryCatalogError(f"catalog entry {name!r} has invalid schema")
        return MemoryTarget(
            name,
            "postgresql",
            evidence_root,
            connection_env=connection_env,
            postgres_schema=schema,
            connection_value=os.environ.get(connection_env),
        )

    def _read_entries(self) -> dict[str, MemoryTarget]:
        if not self.catalog_path.exists():
            self._validate_disjoint({})
            return {}
        if not self.catalog_path.is_file() or self.catalog_path.is_symlink():
            raise MemoryCatalogError("memory catalog must be a regular file")
        try:
            document = strict_json_loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MemoryCatalogError("cannot read memory catalog") from exc
        if not isinstance(document, dict) or set(document) != {"version", "memories"}:
            raise MemoryCatalogError("memory catalog has invalid top-level fields")
        if document["version"] != 1 or not isinstance(document["memories"], dict):
            raise MemoryCatalogError("memory catalog version or memories is invalid")
        result: dict[str, MemoryTarget] = {}
        for name, raw in document["memories"].items():
            if not isinstance(name, str):
                raise MemoryCatalogError("memory catalog names must be strings")
            _validate_name(name)
            result[name] = self._parse_target(name, raw)
        self._validate_disjoint(result)
        return result

    def _validate_disjoint(self, entries: dict[str, MemoryTarget]) -> None:
        targets = [self._default_target(), *entries.values()]
        evidence_roots = [target.evidence_root for target in targets]
        for target in targets:
            if target.backend == "sqlite":
                assert target.database is not None
                if any(
                    _paths_overlap(target.database, root) for root in evidence_roots
                ):
                    raise MemoryCatalogError(
                        f"SQLite target for {target.name!r} is inside an evidence root"
                    )
        for index, left in enumerate(targets):
            for right in targets[index + 1 :]:
                if _paths_overlap(left.evidence_root, right.evidence_root):
                    raise MemoryCatalogError(
                        f"evidence roots for {left.name!r} and {right.name!r} overlap"
                    )
                if (
                    left.backend == right.backend == "sqlite"
                    and left.database == right.database
                ):
                    raise MemoryCatalogError(
                        f"SQLite targets for {left.name!r} and {right.name!r} match"
                    )
                if (
                    left.backend == right.backend == "postgresql"
                    and left.postgres_schema == right.postgres_schema
                    and (
                        left.connection_env == right.connection_env
                        or (
                            left.connection_value is not None
                            and left.connection_value == right.connection_value
                        )
                    )
                ):
                    raise MemoryCatalogError(
                        f"PostgreSQL targets for {left.name!r} and {right.name!r} match"
                    )

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.catalog_path.with_suffix(self.catalog_path.suffix + ".lock")
        descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        os.chmod(lock, 0o600)
        if os.name == "nt" and os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        deadline = time.monotonic() + 10
        locked = False
        while not locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    locking = msvcrt.locking  # type: ignore[attr-defined]
                    mode = msvcrt.LK_NBLCK  # type: ignore[attr-defined]
                    locking(descriptor, mode, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(descriptor)
                    raise MemoryCatalogError("memory catalog is locked") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                unlocking = msvcrt.locking  # type: ignore[attr-defined]
                mode = msvcrt.LK_UNLCK  # type: ignore[attr-defined]
                unlocking(descriptor, mode, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _write_entries(self, entries: dict[str, MemoryTarget]) -> None:
        document = {
            "version": 1,
            "memories": {name: entries[name].document() for name in sorted(entries)},
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.catalog_path.name}.", dir=self.catalog_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(canonical_json(document))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.catalog_path)
            os.chmod(self.catalog_path, 0o600)
            if os.name != "nt":
                parent_descriptor = os.open(self.catalog_path.parent, os.O_RDONLY)
                try:
                    os.fsync(parent_descriptor)
                finally:
                    os.close(parent_descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    def catalog(self) -> dict[str, Any]:
        entries = self._read_entries()
        default = self._default_target().document()
        default["source"] = "environment"
        return {
            "default": "default",
            "memories": {
                "default": default,
                **{
                    name: {**target.document(), "source": "catalog"}
                    for name, target in sorted(entries.items())
                },
            },
            "version": 1,
        }

    def agent_catalog(self) -> dict[str, Any]:
        catalog = self.catalog()
        memories = {}
        for name, target in catalog["memories"].items():
            capabilities = (
                "memory://capabilities/current"
                if name == "default"
                else f"memory://memories/{name}/capabilities/current"
            )
            ontology = (
                "memory://schema/ontology/current"
                if name == "default"
                else f"memory://memories/{name}/schema/ontology/current"
            )
            memories[name] = {
                **target,
                "capabilities": capabilities,
                "content": "unknown_until_summary",
                "ontology": ontology,
                "summary": f"memory://memories/{name}/summary",
            }
        return {
            **catalog,
            "agent_catalog_version": "1",
            "memories": memories,
            "selection_note": (
                "An empty default memory does not imply that named memories are empty. "
                "Read a memory summary before making a content claim."
            ),
        }

    def _application(self, target: MemoryTarget) -> MemoryApplication:
        if target.backend == "sqlite":
            return build_application(
                database=target.database,
                evidence_root=target.evidence_root,
                schema_path=None,
                backend="sqlite",
            )
        assert target.connection_env is not None
        dsn = os.environ.get(target.connection_env)
        if not dsn:
            raise MemoryUnavailableError(
                f"memory {target.name!r} is unavailable",
                details={
                    "memory": target.name,
                    "reason": "connection environment variable is not set",
                },
            )
        return build_application(
            evidence_root=target.evidence_root,
            schema_path=None,
            backend="postgresql",
            postgres_url=dsn,
            postgres_schema=target.postgres_schema,
        )

    @staticmethod
    def _validate_application(application: MemoryApplication) -> list[str]:
        issues: list[str] = []
        memory_status = application.memory_store.status()
        if not memory_status.initialized:
            issues.append("memory store is not initialized")
        evidence_status = application.evidence_store.status()
        if not evidence_status.initialized:
            issues.append("evidence store is not initialized")
        if memory_status.initialized:
            integrity = application.memory_store.integrity()
            if not integrity["ok"]:
                issues.append("memory store integrity or migration ledger failed")
        return issues

    @staticmethod
    def _cache_key(target: MemoryTarget) -> str:
        return canonical_json(
            {
                **target.document(),
                "connection_digest": (
                    None
                    if target.connection_value is None
                    else sha256_json(target.connection_value)
                ),
            }
        )

    def resolve(self, memory: str | None = None) -> tuple[str, MemoryApplication]:
        name = "default" if memory is None else memory
        if name == "default":
            return name, self.default_application
        entries = self._read_entries()
        target = entries.get(name)
        if target is None:
            raise MemoryNotFoundError(
                f"memory {name!r} is not configured", details={"memory": name}
            )
        cache_key = self._cache_key(target)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            return name, cached
        try:
            application = self._application(target)
            issues = self._validate_application(application)
        except MemoryUnavailableError:
            raise
        except Exception as exc:
            raise MemoryUnavailableError(
                f"memory {name!r} is unavailable",
                details={"memory": name, "reason": type(exc).__name__},
            ) from exc
        if issues:
            raise MemoryUnavailableError(
                f"memory {name!r} is unavailable",
                details={"memory": name, "reason": "; ".join(issues)},
            )
        self._cache[cache_key] = application
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return name, application

    @staticmethod
    def _require_create_target(target: MemoryTarget) -> None:
        if target.evidence_root.exists() and (
            not target.evidence_root.is_dir() or any(target.evidence_root.iterdir())
        ):
            raise MemoryCatalogError("create requires a new or empty evidence root")
        if target.backend == "sqlite":
            assert target.database is not None
            if target.database.exists() and (
                not target.database.is_file() or target.database.stat().st_size != 0
            ):
                raise MemoryCatalogError("create requires a new or empty SQLite file")

    @staticmethod
    def _require_attach_target(target: MemoryTarget) -> None:
        if not target.evidence_root.is_dir():
            raise MemoryCatalogError("attach requires an existing evidence root")
        if target.backend == "sqlite":
            assert target.database is not None
            if not target.database.is_file() or target.database.stat().st_size == 0:
                raise MemoryCatalogError("attach requires an existing SQLite database")

    def configure(
        self,
        *,
        action: Literal["create", "attach"],
        name: str,
        backend: MemoryBackend,
        evidence_root: str | Path,
        database: str | Path | None = None,
        connection_env: str | None = None,
        postgres_schema: str | None = None,
    ) -> dict[str, Any]:
        _validate_name(name)
        raw: dict[str, Any] = {
            "backend": backend,
            "evidence_root": str(evidence_root),
        }
        if backend == "sqlite":
            if (
                database is None
                or connection_env is not None
                or postgres_schema is not None
            ):
                raise MemoryCatalogError(
                    "SQLite requires only database and evidence_root"
                )
            raw["database"] = str(database)
        elif backend == "postgresql":
            if (
                database is not None
                or connection_env is None
                or postgres_schema is None
            ):
                raise MemoryCatalogError(
                    "PostgreSQL requires connection_env, schema, and evidence_root"
                )
            raw["connection_env"] = connection_env
            raw["schema"] = postgres_schema
        else:
            raise MemoryCatalogError("backend must be sqlite or postgresql")
        target = self._parse_target(name, raw)
        with self._write_lock():
            entries = self._read_entries()
            if name in entries:
                raise MemoryCatalogError(f"memory {name!r} is already configured")
            candidate = {**entries, name: target}
            self._validate_disjoint(candidate)
            try:
                application = self._application(target)
                created_postgres_schema = False
                if action == "create":
                    self._require_create_target(target)
                    if backend == "postgresql":
                        created_postgres_schema = self._prepare_postgres_create(
                            application
                        )
                    try:
                        application.initialize()
                    except Exception:
                        if created_postgres_schema:
                            self._drop_postgres_schema(application)
                        raise
                elif action == "attach":
                    self._require_attach_target(target)
                    issues = self._validate_application(application)
                    if issues:
                        raise MemoryCatalogError(
                            "attach target is not compatible",
                            details={"memory": name, "issues": issues},
                        )
                else:
                    raise MemoryCatalogError("action must be create or attach")
            except (MemoryCatalogError, MemoryUnavailableError):
                raise
            except Exception as exc:
                raise MemoryUnavailableError(
                    f"memory {name!r} target could not be configured",
                    details={"memory": name, "reason": type(exc).__name__},
                ) from exc
            self._write_entries(candidate)
        return {"action": action, "memory": name, "target": target.document()}

    def lifecycle(
        self,
        *,
        action: Literal["wipe", "delete"],
        memory: str,
        expected_state: dict[str, int | str],
    ) -> dict[str, Any]:
        expected_fields = {
            "active_relations",
            "attributes",
            "evidence_objects",
            "fingerprint",
            "nodes",
        }
        counts = {
            key: value for key, value in expected_state.items() if key != "fingerprint"
        }
        fingerprint = expected_state.get("fingerprint")
        if (
            set(expected_state) != expected_fields
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in counts.values()
            )
            or not isinstance(fingerprint, str)
            or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
        ):
            raise MemoryCatalogError(
                "expected_state must contain non-negative integer counts for "
                "nodes, attributes, active_relations, and evidence_objects plus "
                "the exact lowercase SHA-256 fingerprint"
            )
        if action not in {"wipe", "delete"}:
            raise MemoryCatalogError("action must be wipe or delete")
        if action == "delete" and memory == "default":
            raise MemoryCatalogError("default memory cannot be deleted; use wipe")

        with self._write_lock():
            entries = self._read_entries()
            if memory == "default":
                target = self._default_target()
                application = self.default_application
            else:
                named_target = entries.get(memory)
                if named_target is None:
                    raise MemoryNotFoundError(
                        f"memory {memory!r} is not configured",
                        details={"memory": memory},
                    )
                target = named_target
                application = self._application(target)
                issues = self._validate_application(application)
                if issues:
                    raise MemoryUnavailableError(
                        f"memory {memory!r} is unavailable",
                        details={"memory": memory, "reason": "; ".join(issues)},
                    )

            actual_state = application.memory_store.lifecycle_state()
            if actual_state != expected_state:
                raise MemoryStateChangedError(
                    "memory state changed; inspect it and retry with current counts",
                    details={
                        "actual_state": actual_state,
                        "expected_state": expected_state,
                        "memory": memory,
                    },
                )

            self._require_wipeable_evidence_root(target)
            try:
                if action == "delete":
                    removed = application.memory_store.destroy(expected_state)
                else:
                    removed = application.memory_store.wipe(expected_state)
            except MemoryStateChangedError as exc:
                exc.details.setdefault("memory", memory)
                raise
            except MemoryLifecycleError:
                raise
            except Exception as exc:
                raise MemoryLifecycleError(
                    "memory store lifecycle operation failed",
                    details={"action": action, "memory": memory},
                ) from exc
            self._cache.clear()
            try:
                removed.update(application.evidence_store.wipe())
            except Exception as exc:
                raise MemoryLifecycleError(
                    "canonical state was wiped but evidence removal failed",
                    details={
                        "canonical_removed": True,
                        "catalog_entry_removed": False,
                        "evidence_removed": False,
                        "memory": memory,
                    },
                ) from exc
            catalog_entry_removed = False
            if action == "delete":
                try:
                    self._remove_target_storage(target)
                    del entries[memory]
                    self._write_entries(entries)
                    catalog_entry_removed = True
                except Exception as exc:
                    raise MemoryLifecycleError(
                        "memory content was wiped but named target removal failed",
                        details={
                            "canonical_removed": True,
                            "catalog_entry_removed": False,
                            "evidence_removed": True,
                            "memory": memory,
                        },
                    ) from exc
        return {
            "action": action,
            "catalog_entry_removed": catalog_entry_removed,
            "memory": memory,
            "removed": removed,
            "target": target.document(),
        }

    def lifecycle_status(self, memory: str) -> dict[str, Any]:
        entries = self._read_entries()
        if memory == "default":
            selected = "default"
            target = self._default_target()
            application = self.default_application
        else:
            selected = memory
            named_target = entries.get(memory)
            if named_target is None:
                raise MemoryNotFoundError(
                    f"memory {memory!r} is not configured",
                    details={"memory": memory},
                )
            target = named_target
            application = self._application(target)
            issues = self._validate_application(application)
            if issues:
                raise MemoryUnavailableError(
                    f"memory {memory!r} is unavailable",
                    details={"memory": memory, "reason": "; ".join(issues)},
                )
        try:
            state = application.memory_store.lifecycle_state()
        except Exception as exc:
            raise MemoryUnavailableError(
                f"memory {memory!r} lifecycle state is unavailable",
                details={"memory": memory, "reason": type(exc).__name__},
            ) from exc
        return {"memory": selected, "state": state, "target": target.document()}

    @staticmethod
    def _require_wipeable_evidence_root(target: MemoryTarget) -> None:
        if target.evidence_root.is_symlink() or not target.evidence_root.is_dir():
            raise MemoryCatalogError("evidence root must be a regular directory")

    @staticmethod
    def _remove_target_storage(target: MemoryTarget) -> None:
        if target.backend == "sqlite":
            assert target.database is not None
            target.database.unlink(missing_ok=True)
            for suffix in ("-shm", "-wal"):
                Path(f"{target.database}{suffix}").unlink(missing_ok=True)
        if target.evidence_root.exists():
            if target.evidence_root.is_symlink() or not target.evidence_root.is_dir():
                raise MemoryCatalogError("evidence root must be a regular directory")
            shutil.rmtree(target.evidence_root)

    @staticmethod
    def _prepare_postgres_create(application: MemoryApplication) -> bool:
        from analytical_memory.adapters.postgresql import PostgresMemoryStore

        store = application.memory_store
        assert isinstance(store, PostgresMemoryStore)
        import psycopg
        from psycopg import sql

        with psycopg.connect(store.dsn) as connection:
            exists_row = connection.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.schemata "
                "WHERE schema_name = %s)",
                (store.schema,),
            ).fetchone()
            if exists_row is None:
                raise MemoryCatalogError("cannot inspect PostgreSQL schema")
            exists = bool(exists_row[0])
            if exists:
                occupied_row = connection.execute(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid = c.relnamespace WHERE n.nspname = %s "
                    "UNION ALL SELECT 1 FROM pg_proc p JOIN pg_namespace n "
                    "ON n.oid = p.pronamespace WHERE n.nspname = %s "
                    "UNION ALL SELECT 1 FROM pg_type t JOIN pg_namespace n "
                    "ON n.oid = t.typnamespace WHERE n.nspname = %s"
                    ")",
                    (store.schema, store.schema, store.schema),
                ).fetchone()
                if occupied_row is None:
                    raise MemoryCatalogError("cannot inspect PostgreSQL schema")
                if bool(occupied_row[0]):
                    raise MemoryCatalogError(
                        "create requires an absent or empty PostgreSQL schema"
                    )
                return False
            else:
                connection.execute(
                    sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(store.schema))
                )
                return True

    @staticmethod
    def _drop_postgres_schema(application: MemoryApplication) -> None:
        from analytical_memory.adapters.postgresql import PostgresMemoryStore

        store = application.memory_store
        assert isinstance(store, PostgresMemoryStore)
        import psycopg
        from psycopg import sql

        with psycopg.connect(store.dsn) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(store.schema))
            )
