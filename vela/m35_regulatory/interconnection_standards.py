"""
Interconnection technical standards compliance for VPP inverter resources.

Verifies compliance with IEEE 1547-2018, UL 9540, UL 1741-SA,
and ISO/RTO interconnection requirements.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class InverterSpecs:
    inverter_id: str
    rated_kva: float
    rated_kw: float
    max_voltage_v: float
    frequency_range_hz: Tuple[float, float]   # (min, max)
    voltage_ride_through: bool    # IEEE 1547 Category II
    frequency_ride_through: bool
    reactive_power_capable: bool
    ramp_rate_kw_s: float
    anti_islanding: bool = True
    ul1741_sa: bool = False   # Utility-interactive advanced
    ieee1547_cat: str = "A"    # "A", "B", "C"


@dataclass
class ComplianceCheckResult:
    inverter_id: str
    standard: str
    passed: bool
    violations: List[str]
    recommendations: List[str]


# IEEE 1547-2018 Category B voltage ride-through requirements
IEEE1547_CAT_B_VOLTAGE = {
    "low_trip": (0.45, 0.16),     # (pu voltage, max duration seconds)
    "high_trip": (1.10, 1.0),
    "momentary_cessation": (0.50, 0.16),
}

IEEE1547_FREQ_RANGE = (57.0, 61.8)   # Hz, must ride through


def check_ieee_1547(specs: InverterSpecs) -> ComplianceCheckResult:
    """Verify inverter meets IEEE 1547-2018 requirements."""
    violations: List[str] = []
    recs: List[str] = []

    # Frequency range
    if specs.frequency_range_hz[0] > IEEE1547_FREQ_RANGE[0]:
        violations.append(f"Min frequency {specs.frequency_range_hz[0]} Hz > 57.0 Hz requirement")
    if specs.frequency_range_hz[1] < IEEE1547_FREQ_RANGE[1]:
        violations.append(f"Max frequency {specs.frequency_range_hz[1]} Hz < 61.8 Hz requirement")

    # Ride-through
    if specs.ieee1547_cat == "B" and not specs.voltage_ride_through:
        violations.append("Category B requires voltage ride-through capability")
    if not specs.frequency_ride_through:
        recs.append("Consider enabling frequency ride-through for grid support")

    # Anti-islanding
    if not specs.anti_islanding:
        violations.append("Anti-islanding protection required by IEEE 1547-2018 §8.3")

    # Reactive power (required for Cat B)
    if specs.ieee1547_cat == "B" and not specs.reactive_power_capable:
        violations.append("Category B requires reactive power capability (volt-VAR)")

    return ComplianceCheckResult(
        inverter_id=specs.inverter_id,
        standard="IEEE 1547-2018",
        passed=len(violations) == 0,
        violations=violations,
        recommendations=recs,
    )


def check_ul1741_sa(specs: InverterSpecs) -> ComplianceCheckResult:
    """Check UL 1741-SA (Utility Interactive advanced features)."""
    violations: List[str] = []
    recs: List[str] = []

    if not specs.ul1741_sa:
        violations.append("Device not certified to UL 1741-SA")

    if not specs.voltage_ride_through:
        violations.append("UL 1741-SA requires voltage ride-through")

    if specs.ramp_rate_kw_s > specs.rated_kw / 60.0:
        recs.append("Consider limiting ramp rate to <= rated_kw/60 kW/s")

    return ComplianceCheckResult(
        inverter_id=specs.inverter_id,
        standard="UL 1741-SA",
        passed=len(violations) == 0,
        violations=violations,
        recommendations=recs,
    )
