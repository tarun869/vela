"""
Alert engine for VPP operational and market notifications.

Routes alerts to appropriate channels based on severity, on-call schedule,
and notification preferences with deduplication and escalation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class Channel(str, Enum):
    EMAIL = "email"
    SLACK = "slack"
    SMS = "sms"
    PAGERDUTY = "pagerduty"


@dataclass
class Alert:
    alert_id: str
    title: str
    message: str
    severity: Severity
    source: str
    tags: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    suppressed: bool = False


@dataclass
class NotificationRule:
    rule_id: str
    severity_min: Severity
    channels: List[Channel]
    recipients: List[str]
    dedup_window_s: int = 300   # Suppress duplicate alerts within this window


SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.WARNING: 1,
    Severity.CRITICAL: 2,
    Severity.EMERGENCY: 3,
}


class AlertEngine:
    """
    Routes VPP operational alerts through configured notification channels.

    Features:
    - Deduplication window to suppress repeated alerts
    - Severity-based channel routing
    - Escalation after acknowledgement timeout
    """

    def __init__(self) -> None:
        self._rules: List[NotificationRule] = []
        self._dispatchers: Dict[Channel, Callable[[Alert, List[str]], bool]] = {}
        self._sent_history: List[Dict[str, Any]] = []
        self._dedup_map: Dict[str, float] = {}   # alert title hash -> last sent time

    def register_rule(self, rule: NotificationRule) -> None:
        self._rules.append(rule)

    def register_dispatcher(
        self, channel: Channel, dispatcher: Callable[[Alert, List[str]], bool]
    ) -> None:
        self._dispatchers[channel] = dispatcher

    def _is_duplicate(self, alert: Alert, window_s: int) -> bool:
        key = f"{alert.source}:{alert.title}"
        last_sent = self._dedup_map.get(key, 0.0)
        if time.time() - last_sent < window_s:
            return True
        self._dedup_map[key] = time.time()
        return False

    def fire(self, alert: Alert) -> Dict[Channel, bool]:
        """
        Process an alert and dispatch to matching channels.

        Returns dict of channel -> dispatch success.
        """
        if alert.suppressed:
            return {}

        results: Dict[Channel, bool] = {}

        for rule in self._rules:
            if SEVERITY_ORDER[alert.severity] < SEVERITY_ORDER[rule.severity_min]:
                continue
            if self._is_duplicate(alert, rule.dedup_window_s):
                continue
            for channel in rule.channels:
                dispatcher = self._dispatchers.get(channel)
                if dispatcher:
                    success = dispatcher(alert, rule.recipients)
                    results[channel] = success
                    self._sent_history.append({
                        "alert_id": alert.alert_id,
                        "channel": channel.value,
                        "recipients": rule.recipients,
                        "success": success,
                        "timestamp": time.time(),
                    })

        return results

    def recent_alerts(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(reversed(self._sent_history[-limit:]))
