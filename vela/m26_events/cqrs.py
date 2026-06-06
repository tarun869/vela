"""
CQRS (Command Query Responsibility Segregation) pattern for VPP operations.

Separates write-side commands (with validation and business rules)
from read-side queries (optimized projections for dashboards and APIs).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Command side
# ---------------------------------------------------------------------------

@dataclass
class Command:
    command_type: str
    payload: Dict[str, Any]
    issued_by: str
    timestamp: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None


@dataclass
class CommandResult:
    success: bool
    command_type: str
    aggregate_id: Optional[str] = None
    error: Optional[str] = None
    events_raised: int = 0


class CommandBus:
    """Routes commands to registered handler functions."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[Command], CommandResult]] = {}

    def register(self, command_type: str, handler: Callable[[Command], CommandResult]) -> None:
        self._handlers[command_type] = handler

    def dispatch(self, command: Command) -> CommandResult:
        handler = self._handlers.get(command.command_type)
        if not handler:
            return CommandResult(success=False, command_type=command.command_type,
                                 error=f"No handler for {command.command_type}")
        try:
            return handler(command)
        except Exception as exc:
            return CommandResult(success=False, command_type=command.command_type, error=str(exc))


# ---------------------------------------------------------------------------
# Query side
# ---------------------------------------------------------------------------

@dataclass
class QueryResult(Generic[T]):
    success: bool
    data: Optional[T]
    error: Optional[str] = None
    cached: bool = False
    latency_ms: float = 0.0


class ReadModelStore:
    """
    Simple key-value read model store for CQRS projections.

    In production, this would be a materialized view in PostgreSQL or Redis.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

    def upsert(self, key: str, value: Any) -> None:
        self._store[key] = value

    def get(self, key: str) -> Optional[Any]:
        return self._store.get(key)

    def query(self, prefix: str) -> Dict[str, Any]:
        return {k: v for k, v in self._store.items() if k.startswith(prefix)}


class QueryBus:
    """Routes read-side queries to projection handlers."""

    def __init__(self, store: ReadModelStore) -> None:
        self._store = store
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}

    def register(self, query_type: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        self._handlers[query_type] = handler

    def execute(self, query_type: str, params: Dict[str, Any]) -> QueryResult:
        start = time.time()
        handler = self._handlers.get(query_type)
        if not handler:
            return QueryResult(success=False, data=None, error=f"No handler for {query_type}")
        try:
            data = handler(params)
            return QueryResult(
                success=True, data=data,
                latency_ms=(time.time() - start) * 1000
            )
        except Exception as exc:
            return QueryResult(success=False, data=None, error=str(exc))
