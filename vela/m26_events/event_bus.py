"""
In-process event bus for decoupled VPP module communication.

Implements publish-subscribe pattern with typed event routing,
async-compatible dispatch, and dead-letter queue for failed handlers.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type


@dataclass
class Event:
    event_type: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    source: str = "vela"
    correlation_id: Optional[str] = None


@dataclass
class DeadLetterEntry:
    event: Event
    handler_name: str
    error: str
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """
    Thread-safe publish-subscribe event bus.

    Supports wildcard subscriptions using "*" event type.
    Failed handlers are captured in a dead-letter queue for diagnostics.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable[[Event], None]]] = defaultdict(list)
        self._dead_letters: List[DeadLetterEntry] = []
        self._lock = threading.RLock()
        self._event_history: List[Event] = []
        self._max_history = 1000

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        """Subscribe a handler function to an event type. Use '*' for all events."""
        with self._lock:
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        """Remove a handler subscription."""
        with self._lock:
            if event_type in self._handlers:
                self._handlers[event_type] = [
                    h for h in self._handlers[event_type] if h is not handler
                ]

    def publish(self, event: Event) -> int:
        """
        Publish an event to all subscribed handlers.

        Returns number of handlers successfully invoked.
        """
        with self._lock:
            handlers = (
                list(self._handlers.get(event.event_type, []))
                + list(self._handlers.get("*", []))
            )
            # Record history
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)

        success_count = 0
        for handler in handlers:
            try:
                handler(event)
                success_count += 1
            except Exception as exc:
                with self._lock:
                    self._dead_letters.append(DeadLetterEntry(
                        event=event,
                        handler_name=getattr(handler, "__name__", repr(handler)),
                        error=str(exc),
                    ))
        return success_count

    def emit(self, event_type: str, payload: Dict[str, Any], source: str = "vela") -> int:
        """Convenience method to create and publish an event."""
        import uuid
        event = Event(
            event_type=event_type,
            payload=payload,
            source=source,
            correlation_id=str(uuid.uuid4())[:8],
        )
        return self.publish(event)

    def dead_letters(self) -> List[DeadLetterEntry]:
        with self._lock:
            return list(self._dead_letters)

    def history(self, event_type: Optional[str] = None) -> List[Event]:
        with self._lock:
            if event_type:
                return [e for e in self._event_history if e.event_type == event_type]
            return list(self._event_history)

    def clear_dead_letters(self) -> int:
        with self._lock:
            count = len(self._dead_letters)
            self._dead_letters.clear()
            return count


# Module-level singleton bus
_global_bus: Optional[EventBus] = None


def get_bus() -> EventBus:
    """Return the global event bus singleton."""
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus
