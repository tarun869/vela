"""
Regulation Up/Down (frequency regulation) service modeling.

Fast-responding resources (< 5 min) that follow automatic generation
control (AGC) signals to maintain system frequency balance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class RegulationOffer:
    resource_id: str
    reg_up_mw: float
    reg_dn_mw: float
    reg_up_price_usd_mw: float
    reg_dn_price_usd_mw: float
    performance_score: float = 1.0   # CAISO/PJM performance score multiplier
    response_time_s: float = 4.0     # Must be < 5 min
    ramp_rate_mw_min: float = 10.0


@dataclass
class RegulationAssignment:
    resource_id: str
    reg_up_mw: float
    reg_dn_mw: float
    clearing_price_up: float
    clearing_price_dn: float
    performance_payment_usd_h: float
    capacity_payment_usd_h: float


class RegulationScheduler:
    """
    Schedules regulation up/down from VPP battery and inverter resources.

    Batteries are ideal for regulation due to fast, bidirectional response.
    """

    def __init__(
        self,
        iso: str = "PJM",
        reg_up_requirement_mw: float = 200.0,
        reg_dn_requirement_mw: float = 200.0,
        performance_threshold: float = 0.75,
    ) -> None:
        self.iso = iso
        self.req_up = reg_up_requirement_mw
        self.req_dn = reg_dn_requirement_mw
        self.perf_threshold = performance_threshold

    def validate_offer(self, offer: RegulationOffer) -> Tuple[bool, str]:
        if offer.response_time_s > 300:
            return False, "Response time must be < 5 minutes for regulation service"
        if offer.performance_score < self.perf_threshold:
            return False, f"Performance score {offer.performance_score:.2f} < threshold {self.perf_threshold}"
        return True, "OK"

    def clear_market(
        self, offers: List[RegulationOffer]
    ) -> Tuple[List[RegulationAssignment], float, float]:
        """
        Clear regulation market for both up and down.

        Returns:
            (assignments, clearing_price_up, clearing_price_dn)
        """
        valid = [o for o in offers if self.validate_offer(o)[0]]
        valid_up = sorted(valid, key=lambda o: o.reg_up_price_usd_mw)
        valid_dn = sorted(valid, key=lambda o: o.reg_dn_price_usd_mw)

        assignments_map: Dict[str, RegulationAssignment] = {}
        remaining_up = self.req_up
        clearing_up = 0.0

        for offer in valid_up:
            if remaining_up <= 0:
                break
            assigned_up = min(offer.reg_up_mw, remaining_up)
            clearing_up = offer.reg_up_price_usd_mw
            assignments_map[offer.resource_id] = RegulationAssignment(
                resource_id=offer.resource_id,
                reg_up_mw=assigned_up,
                reg_dn_mw=0.0,
                clearing_price_up=clearing_up,
                clearing_price_dn=0.0,
                performance_payment_usd_h=0.0,
                capacity_payment_usd_h=assigned_up * clearing_up,
            )
            remaining_up -= assigned_up

        remaining_dn = self.req_dn
        clearing_dn = 0.0

        for offer in valid_dn:
            if remaining_dn <= 0:
                break
            assigned_dn = min(offer.reg_dn_mw, remaining_dn)
            clearing_dn = offer.reg_dn_price_usd_mw
            if offer.resource_id in assignments_map:
                assignments_map[offer.resource_id].reg_dn_mw = assigned_dn
                assignments_map[offer.resource_id].clearing_price_dn = clearing_dn
                assignments_map[offer.resource_id].capacity_payment_usd_h += assigned_dn * clearing_dn
            else:
                assignments_map[offer.resource_id] = RegulationAssignment(
                    resource_id=offer.resource_id,
                    reg_up_mw=0.0, reg_dn_mw=assigned_dn,
                    clearing_price_up=0.0, clearing_price_dn=clearing_dn,
                    performance_payment_usd_h=0.0,
                    capacity_payment_usd_h=assigned_dn * clearing_dn,
                )
            remaining_dn -= assigned_dn

        # Apply performance payment (PJM: performance * clearing_price * mileage)
        for assignment in assignments_map.values():
            offer = next((o for o in valid if o.resource_id == assignment.resource_id), None)
            if offer:
                assignment.performance_payment_usd_h = (
                    offer.performance_score * (assignment.reg_up_mw + assignment.reg_dn_mw) * 0.1
                )

        return list(assignments_map.values()), clearing_up, clearing_dn
