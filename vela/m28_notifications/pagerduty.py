"""
PagerDuty integration for VPP on-call escalation and incident management.

Uses PagerDuty Events API v2 to trigger, acknowledge, and resolve incidents.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PDIncident:
    dedup_key: str
    summary: str
    source: str
    severity: str         # "critical", "error", "warning", "info"
    custom_details: Dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class PDEventResult:
    status: str           # "success", "failure"
    dedup_key: str
    message: str


class PagerDutyClient:
    """
    PagerDuty Events API v2 client for VPP incident management.

    Simulation mode: records events without making HTTP calls.
    """

    EVENTS_API_URL = "https://events.pagerduty.com/v2/enqueue"

    def __init__(self, routing_key: str = "", simulation: bool = True) -> None:
        self.routing_key = routing_key
        self.simulation = simulation
        self._events: List[Dict] = []

    def _post_event(self, payload: Dict) -> PDEventResult:
        if self.simulation:
            self._events.append({"payload": payload, "timestamp": time.time()})
            return PDEventResult(
                status="success",
                dedup_key=payload.get("dedup_key", "sim-key"),
                message="Simulated success",
            )
        try:
            import urllib.request
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                self.EVENTS_API_URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "X-Routing-Key": self.routing_key,
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                return PDEventResult(
                    status="success",
                    dedup_key=body.get("dedup_key", ""),
                    message=body.get("message", ""),
                )
        except Exception as exc:
            return PDEventResult(status="failure", dedup_key="", message=str(exc))

    def trigger(self, incident: PDIncident) -> PDEventResult:
        """Trigger a new PagerDuty incident."""
        payload = {
            "routing_key": self.routing_key,
            "event_action": "trigger",
            "dedup_key": incident.dedup_key,
            "payload": {
                "summary": incident.summary,
                "source": incident.source,
                "severity": incident.severity,
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(incident.timestamp)
                ),
                "custom_details": incident.custom_details,
            },
        }
        return self._post_event(payload)

    def acknowledge(self, dedup_key: str) -> PDEventResult:
        """Acknowledge an open incident."""
        payload = {
            "routing_key": self.routing_key,
            "event_action": "acknowledge",
            "dedup_key": dedup_key,
        }
        return self._post_event(payload)

    def resolve(self, dedup_key: str) -> PDEventResult:
        """Resolve an open incident."""
        payload = {
            "routing_key": self.routing_key,
            "event_action": "resolve",
            "dedup_key": dedup_key,
        }
        return self._post_event(payload)

    def active_incidents(self) -> List[Dict]:
        """Return triggered but unresolved incidents (simulation)."""
        triggered = {e["payload"]["dedup_key"] for e in self._events
                     if e["payload"].get("event_action") == "trigger"}
        resolved = {e["payload"]["dedup_key"] for e in self._events
                    if e["payload"].get("event_action") == "resolve"}
        return [dk for dk in triggered if dk not in resolved]
