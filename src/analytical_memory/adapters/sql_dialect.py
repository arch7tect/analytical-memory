from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod


class SqlDialect(ABC):
    profile: str

    @property
    @abstractmethod
    def integrity_errors(self) -> tuple[type[Exception], ...]:
        raise NotImplementedError

    @abstractmethod
    def rewrite(self, statement: str) -> str:
        raise NotImplementedError


class SqliteDialect(SqlDialect):
    profile = "sqlite"

    @property
    def integrity_errors(self) -> tuple[type[Exception], ...]:
        return (sqlite3.IntegrityError,)

    def rewrite(self, statement: str) -> str:
        return statement


class PostgresDialect(SqlDialect):
    profile = "postgresql"

    def __init__(self, integrity_error: type[Exception]) -> None:
        self._integrity_error = integrity_error

    @property
    def integrity_errors(self) -> tuple[type[Exception], ...]:
        return (self._integrity_error,)

    def rewrite(self, statement: str) -> str:
        normalized = statement.strip()
        if normalized == "BEGIN IMMEDIATE":
            return "SELECT pg_advisory_xact_lock(684321906)"
        if normalized == "PRAGMA defer_foreign_keys = ON":
            return "SET CONSTRAINTS ALL DEFERRED"
        result: list[str] = []
        in_string = False
        index = 0
        while index < len(statement):
            character = statement[index]
            if character == "'":
                result.append(character)
                if (
                    in_string
                    and index + 1 < len(statement)
                    and statement[index + 1] == "'"
                ):
                    result.append("'")
                    index += 2
                    continue
                in_string = not in_string
            elif character == "?" and not in_string:
                result.append("%s")
            else:
                result.append(character)
            index += 1
        return "".join(result)
