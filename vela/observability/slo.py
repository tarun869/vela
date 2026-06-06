"""Service Level Objective (SLO) tracking and alerting."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SLODefinition:
    name: str
    description: str
    target: float  # e.g. 0.999 for 99.9% availability
    window_seconds: int = 86400  # rolling 24-hour window


@dataclass
class SLOState:
    definition: SLODefinition
    _events: list[tuple[float, bool]] = field(default_factory=list)  # (timestamp, success)

    def record(self, success: bool) -> None:
        self._events.append((time.monotonic(), success))
        self._evict_old()

    def _evict_old(self) -> None:
        cutoff = time.monotonic() - self.definition.window_seconds
        self._events = [(ts, ok) for ts, ok in self._events if ts > cutoff]

    @property
    def current_slo(self) -> float:
        if not self._events:
            return 1.0
        successes = sum(1 for _, ok in self._events if ok)
        return successes / len(self._events)

    @property
    def is_violating(self) -> bool:
        return self.current_slo < self.definition.target

    @property
    def error_budget_remaining(self) -> float:
        """Fraction of error budget remaining. Negative means budget exhausted."""
        allowed_error = 1.0 - self.definition.target
        actual_error = 1.0 - self.current_slo
        if allowed_error == 0:
            return 0.0
        return round(1.0 - actual_error / allowed_error, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.definition.name,
            "target": self.definition.target,
            "current": round(self.current_slo, 5),
            "is_violating": self.is_violating,
            "error_budget_remaining": self.error_budget_remaining,
            "event_count": len(self._events),
            "window_hours": self.definition.window_seconds / 3600,
        }


class SLOTracker:
    """Registry of SLO definitions and their rolling state."""

    def __init__(self) -> None:
        self._states: dict[str, SLOState] = {}

    def register(self, slo: SLODefinition) -> None:
        self._states[slo.name] = SLOState(definition=slo)

    def record(self, name: str, success: bool) -> None:
        state = self._states.get(name)
        if state:
            state.record(success)
        else:
            logger.warning("Unknown SLO: %s", name)

    def get(self, name: str) -> SLOState | None:
        return self._states.get(name)

    def report(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._states.values()]

    def any_violating(self) -> bool:
        return any(s.is_violating for s in self._states.values())


# Default tracker with standard VPP SLOs
tracker = SLOTracker()
tracker.register(SLODefinition("api_availability", "REST API availability", target=0.999))
tracker.register(SLODefinition("dispatch_latency_p95_under_2s", "95th pct dispatch solve < 2s", target=0.95))
tracker.register(SLODefinition("settlement_accuracy", "Settlement reconciliation accuracy", target=0.9999))
tracker.register(SLODefinition("forecast_availability", "Price forecast service availability", target=0.998))
