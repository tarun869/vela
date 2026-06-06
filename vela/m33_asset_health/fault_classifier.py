"""
Fault classification for VPP battery and inverter systems.

Maps raw sensor alarm codes and telemetry patterns to actionable
fault categories with severity and recommended response.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np


class FaultCategory(str, Enum):
    THERMAL = "thermal"
    ELECTRICAL = "electrical"
    COMMUNICATION = "communication"
    MECHANICAL = "mechanical"
    SOFTWARE = "software"
    EXTERNAL = "external"


class FaultSeverity(str, Enum):
    INFORMATIONAL = "informational"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


@dataclass
class FaultPattern:
    fault_code: str
    description: str
    category: FaultCategory
    severity: FaultSeverity
    recommended_action: str
    auto_reset_eligible: bool = False
    dispatch_impact: str = "none"   # "none", "derate", "shutdown"


@dataclass
class FaultEvent:
    asset_id: str
    fault_code: str
    timestamp: float
    active: bool
    raw_telemetry: Optional[Dict[str, float]] = None


@dataclass
class ClassifiedFault:
    event: FaultEvent
    pattern: FaultPattern
    anomaly_score: float   # 0–1: how anomalous the telemetry is


# BESS fault code library (partial)
FAULT_LIBRARY: Dict[str, FaultPattern] = {
    "TH001": FaultPattern("TH001", "Cell over-temperature", FaultCategory.THERMAL, FaultSeverity.CRITICAL,
                          "Shutdown and notify maintenance", dispatch_impact="shutdown"),
    "TH002": FaultPattern("TH002", "Module temp high warning", FaultCategory.THERMAL, FaultSeverity.MAJOR,
                          "Reduce charge/discharge rate", dispatch_impact="derate"),
    "EL001": FaultPattern("EL001", "Cell voltage low", FaultCategory.ELECTRICAL, FaultSeverity.MAJOR,
                          "Prevent deep discharge", dispatch_impact="derate"),
    "EL002": FaultPattern("EL002", "Cell voltage high", FaultCategory.ELECTRICAL, FaultSeverity.MAJOR,
                          "Prevent overcharge", dispatch_impact="derate"),
    "EL003": FaultPattern("EL003", "Ground fault", FaultCategory.ELECTRICAL, FaultSeverity.CRITICAL,
                          "Immediate shutdown", dispatch_impact="shutdown"),
    "CM001": FaultPattern("CM001", "BMS communication timeout", FaultCategory.COMMUNICATION,
                          FaultSeverity.MINOR, "Check cable connections", auto_reset_eligible=True),
    "SW001": FaultPattern("SW001", "SOC estimation drift", FaultCategory.SOFTWARE,
                          FaultSeverity.MINOR, "Recalibrate SOC", auto_reset_eligible=True),
}


class FaultClassifier:
    """Classifies battery fault events and scores anomaly severity."""

    def __init__(self, custom_library: Optional[Dict[str, FaultPattern]] = None) -> None:
        self._library = custom_library or FAULT_LIBRARY

    def classify(self, event: FaultEvent) -> ClassifiedFault:
        """Look up fault code and compute anomaly score from telemetry."""
        pattern = self._library.get(event.fault_code, FaultPattern(
            fault_code=event.fault_code,
            description="Unknown fault",
            category=FaultCategory.ELECTRICAL,
            severity=FaultSeverity.MINOR,
            recommended_action="Investigate manually",
        ))

        # Anomaly score from telemetry z-score
        score = 0.5
        if event.raw_telemetry:
            temps = [v for k, v in event.raw_telemetry.items() if "temp" in k.lower()]
            if temps:
                max_temp = max(temps)
                score = min(1.0, max(0.0, (max_temp - 35.0) / 20.0))

        return ClassifiedFault(event=event, pattern=pattern, anomaly_score=score)

    def active_faults(self, events: List[FaultEvent]) -> List[ClassifiedFault]:
        return [self.classify(e) for e in events if e.active]
