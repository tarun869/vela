"""
Non-spinning (non-synchronous) reserve service modeling.

Non-spinning reserve can respond within 10–30 minutes but does not
need to be currently synchronized to the grid.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple
import numpy as np


@dataclass
class NonSpinOffer:
    resource_id: str
    capacity_mw: float
    price_usd_mw: float
    startup_time_min: float      # Time to reach full output (max 30 min for ERCOT)
    sustained_duration_min: float
    resource_type: str           # "battery", "diesel_gen", "demand_response"


@dataclass
class NonSpinAssignment:
    resource_id: str
    assigned_mw: float
    clearing_price_usd_mw: float
    expected_revenue_usd_h: float


class NonSpinReserveScheduler:
    """Schedules non-spinning reserves from VPP controllable loads and offline generators."""

    def __init__(self, iso: str = "ERCOT", requirement_mw: float = 500.0) -> None:
        self.iso = iso
        self.requirement_mw = requirement_mw

    def clear_market(self, offers: List[NonSpinOffer]) -> Tuple[List[NonSpinAssignment], float]:
        """Clear non-spin market using merit order dispatch."""
        valid = [o for o in offers if o.capacity_mw > 0 and o.startup_time_min <= 30.0]
        valid.sort(key=lambda o: o.price_usd_mw)

        assignments: List[NonSpinAssignment] = []
        remaining = self.requirement_mw
        clearing_price = 0.0

        for offer in valid:
            if remaining <= 0:
                break
            assigned = min(offer.capacity_mw, remaining)
            clearing_price = offer.price_usd_mw
            assignments.append(NonSpinAssignment(
                resource_id=offer.resource_id,
                assigned_mw=assigned,
                clearing_price_usd_mw=clearing_price,
                expected_revenue_usd_h=assigned * clearing_price,
            ))
            remaining -= assigned

        return assignments, clearing_price

    def expected_activation_value(
        self,
        energy_price_usd_mwh: float,
        clearing_price_usd_mw: float,
        activation_probability: float = 0.03,
        duration_h: float = 1.0,
    ) -> float:
        """Compute expected total value: capacity payment + activation energy value."""
        capacity_value = clearing_price_usd_mw
        activation_value = activation_probability * energy_price_usd_mwh * duration_h
        return capacity_value + activation_value
