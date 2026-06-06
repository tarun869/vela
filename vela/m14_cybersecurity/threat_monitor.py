"""
Real-time threat monitoring for the Vela VPP platform.

Aggregates alerts from IDS, audit logs, and network sensors to produce
a unified threat picture with risk scores and escalation triggers.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple
import numpy as np


class ThreatCategory(str, Enum):
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    MALWARE = "malware"
    INSIDER_THREAT = "insider_threat"
    DENIAL_OF_SERVICE = "denial_of_service"
    PROTOCOL_ABUSE = "protocol_abuse"
    DATA_EXFILTRATION = "data_exfiltration"
    COMMAND_INJECTION = "command_injection"


@dataclass
class ThreatIndicator:
    indicator_id: str
    category: ThreatCategory
    severity: float          # 0–10 CVSS-like score
    source: str              # Which subsystem detected it
    timestamp: float
    details: Dict
    mitigated: bool = False


@dataclass
class ThreatAssessment:
    overall_risk_score: float    # 0–100
    threat_level: str            # "GREEN", "YELLOW", "ORANGE", "RED"
    active_indicators: int
    top_threats: List[ThreatIndicator]
    recommended_actions: List[str]
    assessment_time: float


class ThreatMonitor:
    """
    Real-time threat aggregation and scoring engine.

    Aggregates indicators from multiple sources, computes composite
    risk scores, and triggers escalation callbacks.
    """

    RISK_THRESHOLDS = {
        "GREEN": 0,
        "YELLOW": 25,
        "ORANGE": 50,
        "RED": 75,
    }

    def __init__(self) -> None:
        self._indicators: List[ThreatIndicator] = []
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._ip_reputation: Dict[str, float] = {}  # IP -> reputation score (0=bad, 1=clean)
        self._indicator_window_s: float = 3600.0     # 1-hour sliding window
        self._last_assessment: Optional[ThreatAssessment] = None

    def add_indicator(self, indicator: ThreatIndicator) -> None:
        """Add a threat indicator from any source."""
        self._indicators.append(indicator)
        self._trigger_callbacks(indicator)

    def _trigger_callbacks(self, indicator: ThreatIndicator) -> None:
        for cb in self._callbacks.get(indicator.category.value, []):
            cb(indicator)
        if indicator.severity >= 8.0:
            for cb in self._callbacks.get("critical_threat", []):
                cb(indicator)

    def on(self, event: str, callback: Callable) -> None:
        self._callbacks[event].append(callback)

    def _active_indicators(self) -> List[ThreatIndicator]:
        cutoff = time.time() - self._indicator_window_s
        return [i for i in self._indicators if i.timestamp >= cutoff and not i.mitigated]

    def _compute_risk_score(self, indicators: List[ThreatIndicator]) -> float:
        """
        Composite risk score using weighted sum with category multipliers.

        Returns:
            Risk score 0–100.
        """
        if not indicators:
            return 0.0

        category_weights = {
            ThreatCategory.COMMAND_INJECTION: 1.5,
            ThreatCategory.MALWARE: 1.4,
            ThreatCategory.DATA_EXFILTRATION: 1.3,
            ThreatCategory.UNAUTHORIZED_ACCESS: 1.2,
            ThreatCategory.INSIDER_THREAT: 1.2,
            ThreatCategory.DENIAL_OF_SERVICE: 1.1,
            ThreatCategory.PROTOCOL_ABUSE: 1.0,
        }

        weighted_sum = 0.0
        for ind in indicators:
            weight = category_weights.get(ind.category, 1.0)
            weighted_sum += ind.severity * weight

        # Normalize to 0–100 (assumes max severity per indicator is 10)
        max_possible = len(indicators) * 10 * max(category_weights.values())
        raw_score = (weighted_sum / max_possible) * 100 if max_possible > 0 else 0.0

        # Boost for concurrent multi-category threats
        categories_present = len(set(i.category for i in indicators))
        multi_category_boost = min(20.0, categories_present * 5.0)

        return min(100.0, raw_score + multi_category_boost)

    def _threat_level(self, score: float) -> str:
        if score >= self.RISK_THRESHOLDS["RED"]:
            return "RED"
        elif score >= self.RISK_THRESHOLDS["ORANGE"]:
            return "ORANGE"
        elif score >= self.RISK_THRESHOLDS["YELLOW"]:
            return "YELLOW"
        return "GREEN"

    def _recommended_actions(self, indicators: List[ThreatIndicator], threat_level: str) -> List[str]:
        actions = []
        categories = {i.category for i in indicators}

        if ThreatCategory.COMMAND_INJECTION in categories:
            actions.append("Isolate affected control systems immediately")
        if ThreatCategory.MALWARE in categories:
            actions.append("Initiate endpoint isolation and forensic imaging")
        if ThreatCategory.UNAUTHORIZED_ACCESS in categories:
            actions.append("Revoke compromised credentials and rotate keys")
        if threat_level in ("RED", "ORANGE"):
            actions.append("Escalate to SOC and notify NERC CIP contact")
            actions.append("Consider manual override of automated dispatch")
        if threat_level == "RED":
            actions.append("Activate incident response playbook")

        return actions or ["Continue monitoring"]

    def assess(self) -> ThreatAssessment:
        """Compute current threat assessment."""
        active = self._active_indicators()
        score = self._compute_risk_score(active)
        level = self._threat_level(score)
        top_threats = sorted(active, key=lambda i: i.severity, reverse=True)[:5]

        assessment = ThreatAssessment(
            overall_risk_score=score,
            threat_level=level,
            active_indicators=len(active),
            top_threats=top_threats,
            recommended_actions=self._recommended_actions(active, level),
            assessment_time=time.time(),
        )
        self._last_assessment = assessment
        return assessment

    def mitigate(self, indicator_id: str) -> bool:
        """Mark an indicator as mitigated."""
        for ind in self._indicators:
            if ind.indicator_id == indicator_id:
                ind.mitigated = True
                return True
        return False

    def update_ip_reputation(self, ip: str, score: float) -> None:
        """Update IP reputation (0=malicious, 1=trusted)."""
        self._ip_reputation[ip] = max(0.0, min(1.0, score))

    def ip_is_suspicious(self, ip: str, threshold: float = 0.3) -> bool:
        return self._ip_reputation.get(ip, 1.0) < threshold

    def threat_timeline(self, window_h: float = 24.0) -> List[Tuple[float, str, float]]:
        """Return sorted list of (timestamp, category, severity) for timeline view."""
        cutoff = time.time() - window_h * 3600.0
        events = [
            (i.timestamp, i.category.value, i.severity)
            for i in self._indicators if i.timestamp >= cutoff
        ]
        return sorted(events, key=lambda x: x[0])
