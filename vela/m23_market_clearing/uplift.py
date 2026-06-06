"""
Market uplift (make-whole) payment calculation.

Uplift ensures out-of-merit generators recover their avoidable costs
when dispatched for reliability despite being uneconomic at the clearing price.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import numpy as np


@dataclass
class UpliftEligibleResource:
    resource_id: str
    dispatched_mw: float
    clearing_price_usd_mwh: float
    actual_offer_price_usd_mwh: float
    no_load_cost_usd_h: float
    start_cost_usd: float = 0.0
    dispatch_reason: str = "reliability"    # "reliability", "out_of_merit"


@dataclass
class UpliftPayment:
    resource_id: str
    energy_uplift_usd: float       # Covers energy revenue shortfall
    startup_uplift_usd: float      # Covers start cost recovery
    no_load_uplift_usd: float      # Covers fixed online costs
    total_uplift_usd: float
    uplift_category: str           # "reliability", "commitment", "voltage_support"


class UpliftCalculator:
    """
    Calculates ISO-style make-whole uplift payments.

    Make-whole ensures resources with positive costs but negative revenues
    at clearing price still recover avoidable operating costs.
    """

    def __init__(self, socialization_method: str = "load_ratio") -> None:
        """
        Args:
            socialization_method: How to spread uplift costs to load:
                "load_ratio" (proportional to load), "uniform" (per MWh).
        """
        self.socialization = socialization_method

    def compute_uplift(
        self,
        resources: List[UpliftEligibleResource],
        interval_hours: float = 1.0,
    ) -> List[UpliftPayment]:
        """Compute make-whole payment for each eligible resource."""
        payments: List[UpliftPayment] = []
        for res in resources:
            # Energy uplift: shortfall between offer price and clearing price
            energy_revenue = res.dispatched_mw * res.clearing_price_usd_mwh * interval_hours
            energy_cost = res.dispatched_mw * res.actual_offer_price_usd_mwh * interval_hours
            energy_uplift = max(0.0, energy_cost - energy_revenue)

            # No-load cost uplift (hourly fixed cost)
            no_load_uplift = res.no_load_cost_usd_h * interval_hours

            total = energy_uplift + res.start_cost_usd + no_load_uplift
            payments.append(UpliftPayment(
                resource_id=res.resource_id,
                energy_uplift_usd=energy_uplift,
                startup_uplift_usd=res.start_cost_usd,
                no_load_uplift_usd=no_load_uplift,
                total_uplift_usd=total,
                uplift_category=res.dispatch_reason,
            ))
        return payments

    def socialize_uplift(
        self,
        payments: List[UpliftPayment],
        load_by_participant: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Distribute total uplift costs across load-serving entities.

        Returns: {participant_id: uplift_charge_usd}
        """
        total_uplift = sum(p.total_uplift_usd for p in payments)
        total_load = sum(load_by_participant.values())
        result: Dict[str, float] = {}
        for pid, load in load_by_participant.items():
            fraction = load / max(total_load, 1e-9)
            result[pid] = total_uplift * fraction
        return result
