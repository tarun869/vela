"""
Anomaly-based intrusion detection system for the Vela VPP platform.

Uses statistical and behavioral baselines to detect:
  - Unusual command patterns
  - Protocol anomalies (Modbus, DNP3, IEC 61850)
  - Lateral movement indicators
  - Abnormal dispatch sequences
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple
import numpy as np


class ThreatLevel(str, Enum):
    NORMAL = "normal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class NetworkEvent:
    timestamp: float
    source_ip: str
    dest_ip: str
    protocol: str
    command_code: Optional[int]
    payload_size: int
    anomaly_score: float = 0.0


@dataclass
class IDSAlert:
    alert_id: str
    timestamp: float
    threat_level: ThreatLevel
    detection_method: str
    source_ip: str
    description: str
    confidence: float       # 0–1
    recommended_action: str
    raw_event: Optional[NetworkEvent] = None


class StatisticalAnomalyDetector:
    """
    Statistical baseline detector using exponentially weighted moving averages.

    Scores anomalies using z-score on rolling statistics.
    """

    def __init__(
        self,
        window_size: int = 100,
        alpha: float = 0.05,      # EWMA decay factor
        threshold_sigma: float = 3.0,
    ) -> None:
        self.window_size = window_size
        self.alpha = alpha
        self.threshold = threshold_sigma
        self._baselines: Dict[str, Dict[str, float]] = {}  # feature -> {mean, var}
        self._history: Deque[Dict[str, float]] = deque(maxlen=window_size)

    def _update_baseline(self, feature: str, value: float) -> None:
        if feature not in self._baselines:
            self._baselines[feature] = {"mean": value, "var": 1.0, "n": 1}
        else:
            b = self._baselines[feature]
            b["mean"] = (1 - self.alpha) * b["mean"] + self.alpha * value
            b["var"] = (1 - self.alpha) * b["var"] + self.alpha * (value - b["mean"])**2
            b["n"] += 1

    def score(self, features: Dict[str, float]) -> float:
        """
        Compute anomaly score for a feature vector.

        Returns:
            Max z-score across all features (higher = more anomalous).
        """
        max_z = 0.0
        for feat, val in features.items():
            self._update_baseline(feat, val)
            b = self._baselines[feat]
            std = math.sqrt(max(b["var"], 1e-9))
            z = abs(val - b["mean"]) / std
            max_z = max(max_z, z)

        self._history.append(features)
        return max_z

    def is_anomalous(self, features: Dict[str, float]) -> Tuple[bool, float]:
        z = self.score(features)
        return z > self.threshold, z


class RateAnomalyDetector:
    """
    Detects anomalous event rates using sliding window counters.
    Useful for detecting scanning, flooding, and brute-force attacks.
    """

    def __init__(self, window_seconds: float = 60.0, max_normal_rate: int = 100) -> None:
        self.window_seconds = window_seconds
        self.max_normal_rate = max_normal_rate
        self._events: Dict[str, Deque[float]] = {}  # source_ip -> timestamps

    def record_event(self, source: str) -> Tuple[bool, int]:
        """
        Record an event from source and check rate.

        Returns:
            (is_anomalous, current_count_in_window)
        """
        now = time.time()
        if source not in self._events:
            self._events[source] = deque()

        dq = self._events[source]
        dq.append(now)

        # Purge old events
        while dq and now - dq[0] > self.window_seconds:
            dq.popleft()

        count = len(dq)
        return count > self.max_normal_rate, count

    def top_sources(self, n: int = 10) -> List[Tuple[str, int]]:
        """Return top N sources by event rate."""
        rates = [(src, len(dq)) for src, dq in self._events.items()]
        return sorted(rates, key=lambda x: x[1], reverse=True)[:n]


class ProtocolAnomalyDetector:
    """
    Detects anomalies in ICS protocols (Modbus, DNP3, IEC 61850).

    Maintains allowed command sets and flags unexpected function codes.
    """

    ALLOWED_MODBUS_FUNCTIONS = {1, 2, 3, 4, 5, 6, 15, 16}
    MODBUS_WRITE_FUNCTIONS = {5, 6, 15, 16}
    DANGEROUS_DNP3_CODES = {0x81, 0x82}  # Direct operate, select-before-operate

    def __init__(self) -> None:
        self._command_history: Deque[Tuple[float, str, int]] = deque(maxlen=1000)

    def check_modbus(self, source_ip: str, function_code: int) -> Tuple[bool, str]:
        """Check Modbus function code for anomalies."""
        self._command_history.append((time.time(), source_ip, function_code))

        if function_code not in self.ALLOWED_MODBUS_FUNCTIONS:
            return True, f"Unknown Modbus function code {function_code} from {source_ip}"

        if function_code in self.MODBUS_WRITE_FUNCTIONS:
            # Check write frequency — too many writes may indicate spoofing
            now = time.time()
            recent_writes = sum(
                1 for t, src, fc in self._command_history
                if src == source_ip and fc in self.MODBUS_WRITE_FUNCTIONS and now - t < 10.0
            )
            if recent_writes > 20:
                return True, f"Excessive Modbus writes from {source_ip}: {recent_writes} in 10s"

        return False, "OK"

    def check_dnp3(self, source_ip: str, function_code: int) -> Tuple[bool, str]:
        if function_code in self.DANGEROUS_DNP3_CODES:
            return True, f"Dangerous DNP3 function {hex(function_code)} from {source_ip}"
        return False, "OK"


class IntrusionDetectionSystem:
    """
    Composite IDS that aggregates multiple detection methods.
    """

    def __init__(self) -> None:
        self.statistical = StatisticalAnomalyDetector()
        self.rate = RateAnomalyDetector()
        self.protocol = ProtocolAnomalyDetector()
        self._alerts: List[IDSAlert] = []
        self._blocked_ips: set = set()

    def analyze_network_event(self, event: NetworkEvent) -> List[IDSAlert]:
        """Process a network event and return any alerts."""
        import uuid as _uuid
        alerts: List[IDSAlert] = []
        now = time.time()

        if event.source_ip in self._blocked_ips:
            alerts.append(IDSAlert(
                alert_id=str(_uuid.uuid4()),
                timestamp=now,
                threat_level=ThreatLevel.HIGH,
                detection_method="blocklist",
                source_ip=event.source_ip,
                description=f"Traffic from blocked IP {event.source_ip}",
                confidence=0.99,
                recommended_action="drop_and_alert",
                raw_event=event,
            ))

        # Rate check
        is_rate_anom, rate_count = self.rate.record_event(event.source_ip)
        if is_rate_anom:
            alerts.append(IDSAlert(
                alert_id=str(_uuid.uuid4()),
                timestamp=now,
                threat_level=ThreatLevel.MEDIUM,
                detection_method="rate_anomaly",
                source_ip=event.source_ip,
                description=f"High event rate from {event.source_ip}: {rate_count}/min",
                confidence=0.75,
                recommended_action="throttle",
                raw_event=event,
            ))

        # Statistical features
        features = {
            "payload_size": float(event.payload_size),
            "command_code": float(event.command_code or 0),
        }
        is_stat_anom, z_score = self.statistical.is_anomalous(features)
        if is_stat_anom:
            alerts.append(IDSAlert(
                alert_id=str(_uuid.uuid4()),
                timestamp=now,
                threat_level=ThreatLevel.MEDIUM,
                detection_method="statistical",
                source_ip=event.source_ip,
                description=f"Statistical anomaly (z={z_score:.1f}) from {event.source_ip}",
                confidence=min(0.95, z_score / 10.0),
                recommended_action="investigate",
                raw_event=event,
            ))

        # Protocol check
        if event.protocol.lower() == "modbus" and event.command_code is not None:
            is_proto_anom, reason = self.protocol.check_modbus(event.source_ip, event.command_code)
            if is_proto_anom:
                alerts.append(IDSAlert(
                    alert_id=str(_uuid.uuid4()),
                    timestamp=now,
                    threat_level=ThreatLevel.HIGH,
                    detection_method="protocol",
                    source_ip=event.source_ip,
                    description=reason,
                    confidence=0.90,
                    recommended_action="block",
                    raw_event=event,
                ))
                self._blocked_ips.add(event.source_ip)

        self._alerts.extend(alerts)
        return alerts

    def active_threats(self) -> List[IDSAlert]:
        cutoff = time.time() - 3600.0
        return [a for a in self._alerts if a.timestamp >= cutoff and a.threat_level in (ThreatLevel.HIGH, ThreatLevel.CRITICAL)]
