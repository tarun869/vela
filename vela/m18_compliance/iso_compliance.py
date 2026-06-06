"""
ISO/RTO rule compliance checker for VPP market participants.

Validates dispatch schedules, offer formats, and telemetry
requirements for ERCOT, CAISO, PJM, MISO, NYISO, and ISO-NE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class ISO(str, Enum):
    ERCOT = "ERCOT"
    CAISO = "CAISO"
    PJM = "PJM"
    MISO = "MISO"
    NYISO = "NYISO"
    ISONE = "ISONE"
    SPP = "SPP"


@dataclass
class MarketOffer:
    resource_id: str
    iso: ISO
    offer_type: str        # "energy", "reg_up", "reg_dn", "spin", "non_spin"
    capacity_mw: float
    price_usd_mw: float    # $/MW for capacity, $/MWh for energy
    min_runtime_h: float = 0.0
    max_runtime_h: float = 24.0
    ramp_up_mw_min: float = 999.0
    ramp_dn_mw_min: float = 999.0
    response_time_min: float = 10.0
    telemetry_available: bool = True


@dataclass
class ComplianceViolation:
    violation_id: str
    iso: ISO
    rule_reference: str
    description: str
    severity: str   # "reject", "warning", "info"
    suggested_fix: str


class ISOComplianceChecker:
    """
    Validates market offers and dispatch instructions for ISO/RTO compliance.

    Each ISO has specific requirements for offer format, response times,
    minimum capacities, and telemetry.
    """

    # Minimum capacity requirements by ISO and service type (MW)
    MIN_CAPACITY: Dict[str, Dict[str, float]] = {
        "ERCOT": {"energy": 0.1, "reg_up": 0.1, "reg_dn": 0.1, "spin": 0.1, "ers": 0.1},
        "CAISO": {"energy": 0.05, "reg_up": 0.05, "reg_dn": 0.05, "spin": 1.0},
        "PJM": {"energy": 0.1, "reg_d": 0.1, "reg_a": 0.1, "spin": 0.5, "non_spin": 0.5},
        "MISO": {"energy": 0.1, "reg": 1.0, "spin": 0.5},
        "NYISO": {"energy": 0.1, "reg": 1.0, "spin": 1.0},
        "ISONE": {"energy": 0.1, "reg": 0.1, "spin": 0.5},
        "SPP": {"energy": 0.1, "reg": 1.0, "spin": 0.5},
    }

    # Maximum response times by service (minutes)
    MAX_RESPONSE_TIME: Dict[str, Dict[str, float]] = {
        "reg_up": {"ERCOT": 10, "CAISO": 10, "PJM": 5, "MISO": 10},
        "spin": {"ERCOT": 10, "CAISO": 10, "PJM": 10, "MISO": 10},
        "ers": {"ERCOT": 15},
    }

    def validate_offer(self, offer: MarketOffer) -> List[ComplianceViolation]:
        """Validate a market offer against ISO-specific rules."""
        violations: List[ComplianceViolation] = []
        iso_name = offer.iso.value
        import uuid

        # Minimum capacity check
        min_caps = self.MIN_CAPACITY.get(iso_name, {})
        min_cap = min_caps.get(offer.offer_type, 0.0)
        if offer.capacity_mw < min_cap:
            violations.append(ComplianceViolation(
                violation_id=str(uuid.uuid4())[:8],
                iso=offer.iso,
                rule_reference=f"{iso_name} Nodal Protocols §4",
                description=f"Capacity {offer.capacity_mw:.2f} MW below minimum {min_cap:.2f} MW for {offer.offer_type}",
                severity="reject",
                suggested_fix=f"Increase capacity to at least {min_cap} MW or aggregate with other resources",
            ))

        # Response time check
        max_rt = self.MAX_RESPONSE_TIME.get(offer.offer_type, {}).get(iso_name, 999.0)
        if offer.response_time_min > max_rt:
            violations.append(ComplianceViolation(
                violation_id=str(uuid.uuid4())[:8],
                iso=offer.iso,
                rule_reference=f"{iso_name} Ancillary Service Requirements",
                description=f"Response time {offer.response_time_min:.0f} min exceeds {max_rt:.0f} min max",
                severity="reject",
                suggested_fix=f"Ensure resource can respond within {max_rt} minutes",
            ))

        # Telemetry requirement
        if not offer.telemetry_available and offer.offer_type not in ("energy",):
            violations.append(ComplianceViolation(
                violation_id=str(uuid.uuid4())[:8],
                iso=offer.iso,
                rule_reference=f"{iso_name} Telemetry Requirements",
                description="Real-time telemetry required for ancillary services",
                severity="reject",
                suggested_fix="Install ICCP/SCADA telemetry link to ISO before offering ancillary services",
            ))

        # Price cap checks
        price_caps = {"ERCOT": 5000, "CAISO": 2000, "PJM": 2000}
        price_cap = price_caps.get(iso_name, 9999)
        if offer.price_usd_mw > price_cap:
            violations.append(ComplianceViolation(
                violation_id=str(uuid.uuid4())[:8],
                iso=offer.iso,
                rule_reference=f"{iso_name} Offer Cap",
                description=f"Offer price ${offer.price_usd_mw}/MWh exceeds cap ${price_cap}/MWh",
                severity="reject",
                suggested_fix=f"Reduce offer price to below ${price_cap}/MWh",
            ))

        # Non-negative price for regulation down in some ISOs
        if offer.offer_type == "reg_dn" and offer.price_usd_mw < 0 and iso_name in ("ERCOT",):
            violations.append(ComplianceViolation(
                violation_id=str(uuid.uuid4())[:8],
                iso=offer.iso,
                rule_reference="ERCOT Nodal Protocols §6.5",
                description="Negative REGDN offers not allowed in ERCOT",
                severity="warning",
                suggested_fix="Set regulation down offer to >= $0/MWh",
            ))

        return violations

    def validate_dispatch_instruction(
        self,
        iso: ISO,
        resource_id: str,
        dispatched_mw: float,
        offered_mw: float,
        current_output_mw: float,
        ramp_rate_mw_min: float,
        response_time_min: float = 5.0,
    ) -> List[ComplianceViolation]:
        """
        Validate that a dispatch instruction can be physically achieved.
        """
        violations: List[ComplianceViolation] = []
        import uuid

        # Check ramp feasibility
        delta_mw = abs(dispatched_mw - current_output_mw)
        achievable_delta = ramp_rate_mw_min * response_time_min
        if delta_mw > achievable_delta * 1.1:  # 10% tolerance
            violations.append(ComplianceViolation(
                violation_id=str(uuid.uuid4())[:8],
                iso=iso,
                rule_reference="Physical ramp constraint",
                description=f"Dispatch requires {delta_mw:.1f} MW ramp; only {achievable_delta:.1f} MW achievable",
                severity="warning",
                suggested_fix="Pre-position resource or reduce dispatch request",
            ))

        # Check dispatch within offer range
        if dispatched_mw > offered_mw * 1.05:
            violations.append(ComplianceViolation(
                violation_id=str(uuid.uuid4())[:8],
                iso=iso,
                rule_reference=f"{iso.value} Self-Schedule Rules",
                description=f"Dispatch {dispatched_mw:.1f} MW exceeds offered {offered_mw:.1f} MW",
                severity="reject",
                suggested_fix="Increase offer capacity or reduce dispatch acceptance",
            ))

        return violations

    def ercot_4cp_checker(
        self,
        resource_id: str,
        load_profile_mw: List[float],
        four_cp_hours: List[int],
    ) -> Dict[str, float]:
        """
        Check ERCOT 4 Coincident Peak (4CP) compliance.

        Returns dict with peak loads at each 4CP hour.
        """
        return {
            f"4CP_hour_{h}": load_profile_mw[h] if h < len(load_profile_mw) else 0.0
            for h in four_cp_hours
        }
