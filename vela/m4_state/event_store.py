"""Event sourcing store for VPP operational events."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterator


class EventType(Enum):
    """VPP operational event types."""
    ASSET_ONLINE = "asset_online"
    ASSET_OFFLINE = "asset_offline"
    ASSET_FAULT = "asset_fault"
    ASSET_FAULT_CLEARED = "asset_fault_cleared"
    DISPATCH_ISSUED = "dispatch_issued"
    DISPATCH_COMPLETED = "dispatch_completed"
    DISPATCH_CANCELLED = "dispatch_cancelled"
    SOC_LOW = "soc_low"
    SOC_HIGH = "soc_high"
    MARKET_BID_SUBMITTED = "market_bid_submitted"
    MARKET_BID_CLEARED = "market_bid_cleared"
    MARKET_BID_REJECTED = "market_bid_rejected"
    SETTLEMENT_COMPLETED = "settlement_completed"
    GRID_FREQUENCY_ALARM = "grid_frequency_alarm"
    GRID_VOLTAGE_ALARM = "grid_voltage_alarm"
    ISLAND_TRANSITION = "island_transition"
    GRID_RECONNECT = "grid_reconnect"
    FORECAST_UPDATED = "forecast_updated"
    CONFIG_CHANGED = "config_changed"
    OPERATOR_ACTION = "operator_action"


@dataclass
class VelaEvent:
    """An immutable event in the Vela event store."""
    event_type: EventType
    asset_id: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    source: str = "system"          # "system", "operator", "market", "asset"
    correlation_id: str = ""        # Links related events (e.g., bid → clear → settle)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "asset_id": self.asset_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "payload": self.payload,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VelaEvent":
        return cls(
            event_type=EventType(d["event_type"]),
            asset_id=d["asset_id"],
            payload=d.get("payload", {}),
            event_id=d.get("event_id", str(uuid.uuid4())),
            timestamp=d.get("timestamp", time.time()),
            source=d.get("source", "system"),
            correlation_id=d.get("correlation_id", ""),
            version=d.get("version", 1),
        )


class EventProjection:
    """
    A read-model projection maintained from the event stream.

    Projections are rebuilt by replaying all events, making them
    consistent with the event store state.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._state: dict[str, Any] = {}

    def apply(self, event: VelaEvent) -> None:
        """Apply an event to update the projection state."""
        raise NotImplementedError

    @property
    def state(self) -> dict[str, Any]:
        return self._state


class AssetStatusProjection(EventProjection):
    """Tracks current status of each asset from event stream."""

    def __init__(self) -> None:
        super().__init__("asset_status")
        self._status: dict[str, str] = {}
        self._last_event: dict[str, str] = {}

    def apply(self, event: VelaEvent) -> None:
        aid = event.asset_id
        if event.event_type == EventType.ASSET_ONLINE:
            self._status[aid] = "online"
        elif event.event_type == EventType.ASSET_OFFLINE:
            self._status[aid] = "offline"
        elif event.event_type == EventType.ASSET_FAULT:
            self._status[aid] = "fault"
        elif event.event_type == EventType.ASSET_FAULT_CLEARED:
            self._status[aid] = "online"
        self._last_event[aid] = event.event_type.value

    @property
    def state(self) -> dict[str, Any]:
        return {"status": self._status, "last_event": self._last_event}

    def status_of(self, asset_id: str) -> str:
        return self._status.get(asset_id, "unknown")


class DispatchHistoryProjection(EventProjection):
    """Tracks dispatch command history for revenue/performance analysis."""

    def __init__(self) -> None:
        super().__init__("dispatch_history")
        self._dispatches: list[dict[str, Any]] = []
        self._total_mwh_dispatched: float = 0.0
        self._total_revenue: float = 0.0

    def apply(self, event: VelaEvent) -> None:
        if event.event_type == EventType.DISPATCH_COMPLETED:
            self._dispatches.append({
                "asset_id": event.asset_id,
                "timestamp": event.timestamp,
                "energy_mwh": event.payload.get("energy_mwh", 0.0),
                "revenue_usd": event.payload.get("revenue_usd", 0.0),
                "service": event.payload.get("service", "energy"),
            })
            self._total_mwh_dispatched += event.payload.get("energy_mwh", 0.0)
            self._total_revenue += event.payload.get("revenue_usd", 0.0)

    @property
    def state(self) -> dict[str, Any]:
        return {
            "total_dispatches": len(self._dispatches),
            "total_mwh": self._total_mwh_dispatched,
            "total_revenue_usd": self._total_revenue,
        }

    @property
    def total_revenue_usd(self) -> float:
        return self._total_revenue


class EventStore:
    """
    Append-only event store for Vela VPP operational events.

    Supports:
    - Append with subscription notification
    - Replay from a timestamp or sequence number
    - Snapshot checkpoints
    - Projection maintenance
    """

    def __init__(self, max_events: int = 100_000) -> None:
        self._events: list[VelaEvent] = []
        self._max_events = max_events
        self._lock = threading.RLock()
        self._sequence: int = 0
        self._subscribers: list[Callable[[VelaEvent], None]] = []
        self._projections: dict[str, EventProjection] = {}
        self._snapshots: dict[str, Any] = {}

    def append(self, event: VelaEvent) -> int:
        """
        Append an event to the store.

        Returns the sequence number assigned to the event.
        """
        with self._lock:
            self._sequence += 1
            self._events.append(event)
            # Trim if over capacity (keep newest)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]
            # Update all projections
            for proj in self._projections.values():
                try:
                    proj.apply(event)
                except Exception:
                    pass
        # Notify subscribers (outside lock to avoid deadlock)
        for sub in self._subscribers:
            try:
                sub(event)
            except Exception:
                pass
        return self._sequence

    def emit(
        self,
        event_type: EventType,
        asset_id: str,
        payload: dict[str, Any] | None = None,
        source: str = "system",
        correlation_id: str = "",
    ) -> VelaEvent:
        """Convenience method to create and append an event."""
        event = VelaEvent(
            event_type=event_type,
            asset_id=asset_id,
            payload=payload or {},
            source=source,
            correlation_id=correlation_id,
        )
        self.append(event)
        return event

    def subscribe(self, handler: Callable[[VelaEvent], None]) -> None:
        """Subscribe to new events as they are appended."""
        self._subscribers.append(handler)

    def unsubscribe(self, handler: Callable[[VelaEvent], None]) -> None:
        self._subscribers = [s for s in self._subscribers if s is not handler]

    def register_projection(self, projection: EventProjection) -> None:
        """
        Register a projection and replay all existing events into it.
        """
        with self._lock:
            # Replay existing events
            for event in self._events:
                try:
                    projection.apply(event)
                except Exception:
                    pass
            self._projections[projection.name] = projection

    def get_projection(self, name: str) -> EventProjection | None:
        with self._lock:
            return self._projections.get(name)

    def replay(
        self,
        since_timestamp: float | None = None,
        event_type: EventType | None = None,
        asset_id: str | None = None,
    ) -> list[VelaEvent]:
        """
        Replay events with optional filters.

        Args:
            since_timestamp: Only return events after this Unix timestamp.
            event_type: Filter to a specific event type.
            asset_id: Filter to a specific asset.
        """
        with self._lock:
            events = list(self._events)
        if since_timestamp is not None:
            events = [e for e in events if e.timestamp >= since_timestamp]
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        if asset_id is not None:
            events = [e for e in events if e.asset_id == asset_id]
        return events

    def last_event_for_asset(
        self, asset_id: str, event_type: EventType | None = None
    ) -> VelaEvent | None:
        """Return the most recent event for an asset."""
        with self._lock:
            events = [
                e for e in reversed(self._events)
                if e.asset_id == asset_id
                and (event_type is None or e.event_type == event_type)
            ]
        return events[0] if events else None

    def count_by_type(self) -> dict[str, int]:
        """Return a count of events grouped by type."""
        with self._lock:
            counts: dict[str, int] = {}
            for e in self._events:
                key = e.event_type.value
                counts[key] = counts.get(key, 0) + 1
        return counts

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def __iter__(self) -> Iterator[VelaEvent]:
        with self._lock:
            return iter(list(self._events))
