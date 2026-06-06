"""
Event sourcing for VPP aggregate state management.

Stores all state changes as an immutable event log.
Aggregates are rebuilt by replaying events from the store.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Type


@dataclass
class StoredEvent:
    aggregate_id: str
    aggregate_type: str
    event_type: str
    sequence_number: int
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class EventStore:
    """
    Append-only in-memory event store for aggregate event sourcing.

    In production, this would be backed by a Kafka topic or PostgreSQL
    with optimistic concurrency control via sequence numbers.
    """

    def __init__(self) -> None:
        self._streams: Dict[str, List[StoredEvent]] = {}

    def append(
        self,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        payload: Dict[str, Any],
        expected_version: int = -1,
    ) -> StoredEvent:
        """
        Append an event to the aggregate's stream.

        Args:
            expected_version: Optimistic concurrency — raises if current version differs.
                              -1 means any version allowed.
        """
        stream = self._streams.setdefault(aggregate_id, [])
        current_version = len(stream) - 1

        if expected_version >= 0 and current_version != expected_version:
            raise ValueError(
                f"Optimistic concurrency conflict: expected version {expected_version}, "
                f"got {current_version}"
            )

        event = StoredEvent(
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            event_type=event_type,
            sequence_number=len(stream),
            payload=payload,
        )
        stream.append(event)
        return event

    def get_events(
        self,
        aggregate_id: str,
        from_sequence: int = 0,
    ) -> List[StoredEvent]:
        """Retrieve event stream for an aggregate, optionally from a specific version."""
        stream = self._streams.get(aggregate_id, [])
        return [e for e in stream if e.sequence_number >= from_sequence]

    def current_version(self, aggregate_id: str) -> int:
        stream = self._streams.get(aggregate_id, [])
        return len(stream) - 1

    def all_streams(self) -> List[str]:
        return list(self._streams.keys())


class AggregateRoot:
    """
    Base class for event-sourced aggregates.

    Subclasses apply domain events to update state and
    can raise events to be persisted in the event store.
    """

    def __init__(self, aggregate_id: str) -> None:
        self.aggregate_id = aggregate_id
        self._version = -1
        self._pending_events: List[StoredEvent] = []

    def apply_event(self, event: StoredEvent) -> None:
        """Apply a domain event. Subclasses override _handle_event."""
        self._handle_event(event)
        self._version = event.sequence_number

    def _handle_event(self, event: StoredEvent) -> None:
        """Override in subclass to update state from event."""
        pass

    def raise_event(
        self,
        aggregate_type: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        """Queue a new domain event to be persisted."""
        event = StoredEvent(
            aggregate_id=self.aggregate_id,
            aggregate_type=aggregate_type,
            event_type=event_type,
            sequence_number=self._version + len(self._pending_events) + 1,
            payload=payload,
        )
        self._pending_events.append(event)

    def uncommitted_events(self) -> List[StoredEvent]:
        return list(self._pending_events)

    def mark_committed(self) -> None:
        self._pending_events.clear()
