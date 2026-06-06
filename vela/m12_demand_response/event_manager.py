"""
DR Event lifecycle manager.

Manages the full lifecycle of demand response events from signal receipt
through dispatch, performance measurement, and settlement.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class EventStatus(str, Enum):
    PENDING = "pending"           # Received, not yet started
    ACTIVE = "active"             # Currently in effect
    COMPLETED = "completed"       # Successfully completed
    CANCELLED = "cancelled"       # Cancelled before start or during
    FAILED = "failed"             # Site failed to respond
    PENDING_SETTLEMENT = "pending_settlement"


@dataclass
class DREvent:
    event_id: str
    program_id: str
    event_type: str                     # "curtailment", "shift", "modulate"
    start_time: datetime
    end_time: datetime
    target_reduction_kw: float          # Requested load reduction (kW)
    priority: int = 1                   # 1=high, 5=low
    status: EventStatus = EventStatus.PENDING
    issued_at: datetime = field(default_factory=datetime.utcnow)
    cancelled_at: Optional[datetime] = None
    cancellation_reason: str = ""
    notes: str = ""

    @property
    def duration_h(self) -> float:
        return (self.end_time - self.start_time).total_seconds() / 3600.0


@dataclass
class SiteDispatch:
    """Dispatch instruction sent to a specific site for a DR event."""
    dispatch_id: str
    event_id: str
    site_id: str
    enrollment_id: str
    target_kw: float                     # Specific reduction target for this site
    dispatched_at: datetime = field(default_factory=datetime.utcnow)
    acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None


@dataclass
class PerformanceMeasurement:
    event_id: str
    site_id: str
    baseline_kw: float
    actual_kw: float
    reduction_kw: float
    reduction_pct: float
    performance_ratio: float   # actual_reduction / target_reduction
    measurement_period_min: int = 60
    measured_at: datetime = field(default_factory=datetime.utcnow)


class DREventManager:
    """
    Manages the full DR event lifecycle for a VPP fleet.

    Flow: event_received → validate → dispatch_sites → monitor → measure → settle
    """

    def __init__(self) -> None:
        self._events: Dict[str, DREvent] = {}
        self._dispatches: Dict[str, List[SiteDispatch]] = {}  # event_id -> dispatches
        self._measurements: Dict[str, List[PerformanceMeasurement]] = {}
        self._callbacks: Dict[str, List[Callable]] = {
            "event_started": [],
            "event_completed": [],
            "event_cancelled": [],
            "site_dispatched": [],
        }

    def on(self, event_type: str, callback: Callable) -> None:
        """Register a callback for lifecycle events."""
        self._callbacks.setdefault(event_type, []).append(callback)

    def _emit(self, event_type: str, payload: dict) -> None:
        for cb in self._callbacks.get(event_type, []):
            try:
                cb(payload)
            except Exception as e:
                logger.error(f"Callback error for {event_type}: {e}")

    def receive_event(
        self,
        program_id: str,
        event_type: str,
        start_time: datetime,
        end_time: datetime,
        target_reduction_kw: float,
        priority: int = 1,
    ) -> DREvent:
        """Create and register a new DR event."""
        event = DREvent(
            event_id=str(uuid.uuid4()),
            program_id=program_id,
            event_type=event_type,
            start_time=start_time,
            end_time=end_time,
            target_reduction_kw=target_reduction_kw,
            priority=priority,
        )
        self._events[event.event_id] = event
        logger.info(f"DR event received: {event.event_id} for program {program_id}")
        return event

    def dispatch_sites(
        self,
        event_id: str,
        site_allocations: Dict[str, float],   # site_id -> target_kw
        enrollment_map: Dict[str, str],        # site_id -> enrollment_id
    ) -> List[SiteDispatch]:
        """Dispatch DR event to a list of sites with individual targets."""
        event = self._get_event(event_id)
        dispatches: List[SiteDispatch] = []

        for site_id, target_kw in site_allocations.items():
            dispatch = SiteDispatch(
                dispatch_id=str(uuid.uuid4()),
                event_id=event_id,
                site_id=site_id,
                enrollment_id=enrollment_map.get(site_id, ""),
                target_kw=target_kw,
            )
            dispatches.append(dispatch)
            self._emit("site_dispatched", {"event_id": event_id, "site_id": site_id, "target_kw": target_kw})

        self._dispatches[event_id] = dispatches
        return dispatches

    def acknowledge_dispatch(self, dispatch_id: str, event_id: str) -> bool:
        """Mark a site dispatch as acknowledged."""
        for dispatch in self._dispatches.get(event_id, []):
            if dispatch.dispatch_id == dispatch_id:
                dispatch.acknowledged = True
                dispatch.acknowledged_at = datetime.utcnow()
                return True
        return False

    def start_event(self, event_id: str) -> None:
        event = self._get_event(event_id)
        event.status = EventStatus.ACTIVE
        self._emit("event_started", {"event_id": event_id})
        logger.info(f"DR event started: {event_id}")

    def cancel_event(self, event_id: str, reason: str = "") -> None:
        event = self._get_event(event_id)
        if event.status not in (EventStatus.PENDING, EventStatus.ACTIVE):
            raise ValueError(f"Cannot cancel event in state {event.status}")
        event.status = EventStatus.CANCELLED
        event.cancelled_at = datetime.utcnow()
        event.cancellation_reason = reason
        self._emit("event_cancelled", {"event_id": event_id, "reason": reason})

    def record_measurement(
        self,
        event_id: str,
        site_id: str,
        baseline_kw: float,
        actual_kw: float,
    ) -> PerformanceMeasurement:
        """Record actual performance for a site during an event."""
        dispatches = self._dispatches.get(event_id, [])
        target_kw = next((d.target_kw for d in dispatches if d.site_id == site_id), 1.0)
        reduction = baseline_kw - actual_kw
        m = PerformanceMeasurement(
            event_id=event_id,
            site_id=site_id,
            baseline_kw=baseline_kw,
            actual_kw=actual_kw,
            reduction_kw=reduction,
            reduction_pct=reduction / max(baseline_kw, 1.0) * 100.0,
            performance_ratio=reduction / max(target_kw, 1.0),
        )
        self._measurements.setdefault(event_id, []).append(m)
        return m

    def complete_event(self, event_id: str) -> Dict[str, float]:
        """
        Complete an event and return aggregate performance statistics.

        Returns dict with total_reduction_kw, avg_performance_ratio, site_count.
        """
        event = self._get_event(event_id)
        event.status = EventStatus.PENDING_SETTLEMENT
        measurements = self._measurements.get(event_id, [])

        if not measurements:
            event.status = EventStatus.FAILED
            return {"total_reduction_kw": 0.0, "avg_performance_ratio": 0.0, "site_count": 0}

        total_reduction = sum(m.reduction_kw for m in measurements)
        avg_ratio = sum(m.performance_ratio for m in measurements) / len(measurements)

        event.status = EventStatus.COMPLETED
        self._emit("event_completed", {
            "event_id": event_id,
            "total_reduction_kw": total_reduction,
            "avg_performance_ratio": avg_ratio,
        })
        return {
            "total_reduction_kw": total_reduction,
            "avg_performance_ratio": avg_ratio,
            "site_count": len(measurements),
        }

    def get_active_events(self) -> List[DREvent]:
        return [e for e in self._events.values() if e.status == EventStatus.ACTIVE]

    def event_history(self, program_id: Optional[str] = None) -> List[DREvent]:
        events = list(self._events.values())
        if program_id:
            events = [e for e in events if e.program_id == program_id]
        return sorted(events, key=lambda e: e.issued_at, reverse=True)

    def _get_event(self, event_id: str) -> DREvent:
        if event_id not in self._events:
            raise KeyError(f"Event '{event_id}' not found")
        return self._events[event_id]
