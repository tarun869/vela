"""
Spinning reserve (synchronized reserve) service modeling.

Spinning reserve is online capacity that can respond within 10 minutes
to arrest frequency decline following a generation trip event.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class SpinningReserveOffer:
    resource_id: str
    capacity_mw: float          # Reserve capacity offered (MW)
    price_usd_mw: float         # $/MW-hour offer price
    response_time_min: float    # Minimum: must be <= 10 min
    sustained_duration_min: float  # Must sustain for at least 30 min (ISO-specific)
    current_output_mw: float    # Current real-time output
    max_output_mw: float        # Physical maximum output
    online: bool = True         # Must be online (synchronized to grid)


@dataclass
class SpinningReserveAssignment:
    resource_id: str
    assigned_mw: float
    clearing_price_usd_mw: float
    activation_probability: float
    expected_revenue_usd_h: float


class SpinningReserveScheduler:
    """
    Schedules spinning reserve from VPP resources based on ISO requirements.
    """

    def __init__(
        self,
        iso: str = "ERCOT",
        reserve_requirement_mw: float = 1000.0,
        max_response_time_min: float = 10.0,
    ) -> None:
        self.iso = iso
        self.requirement_mw = reserve_requirement_mw
        self.max_response_time = max_response_time_min

    def validate_offer(self, offer: SpinningReserveOffer) -> Tuple[bool, str]:
        """Validate that an offer meets spinning reserve requirements."""
        if not offer.online:
            return False, "Resource must be online (synchronized) for spinning reserve"
        if offer.response_time_min > self.max_response_time:
            return False, f"Response time {offer.response_time_min} min > {self.max_response_time} min max"
        available = offer.max_output_mw - offer.current_output_mw
        if offer.capacity_mw > available + 0.01:
            return False, f"Offered {offer.capacity_mw} MW > available headroom {available:.2f} MW"
        if offer.capacity_mw <= 0:
            return False, "Capacity must be positive"
        return True, "OK"

    def clear_market(
        self, offers: List[SpinningReserveOffer]
    ) -> Tuple[List[SpinningReserveAssignment], float]:
        """
        Clear spinning reserve market using uniform price auction.

        Returns:
            (assignments, clearing_price_usd_mw)
        """
        valid_offers = []
        for offer in offers:
            ok, _ = self.validate_offer(offer)
            if ok:
                valid_offers.append(offer)

        # Sort by price (merit order)
        valid_offers.sort(key=lambda o: o.price_usd_mw)

        assignments: List[SpinningReserveAssignment] = []
        remaining = self.requirement_mw
        clearing_price = 0.0

        for offer in valid_offers:
            if remaining <= 0:
                break
            assigned = min(offer.capacity_mw, remaining)
            clearing_price = offer.price_usd_mw
            assignments.append(SpinningReserveAssignment(
                resource_id=offer.resource_id,
                assigned_mw=assigned,
                clearing_price_usd_mw=clearing_price,
                activation_probability=0.05,  # Typical ~5% activation rate
                expected_revenue_usd_h=assigned * clearing_price,
            ))
            remaining -= assigned

        return assignments, clearing_price

    def co_optimize_energy_spin(
        self,
        energy_prices: List[float],
        spin_prices: List[float],
        capacity_mw: float,
        min_spin_fraction: float = 0.10,
    ) -> List[Tuple[float, float]]:
        """
        Co-optimize energy dispatch and spinning reserve allocation.

        Returns list of (energy_mw, spin_mw) per period.
        """
        results: List[Tuple[float, float]] = []
        for ep, sp in zip(energy_prices, spin_prices):
            # Simple: allocate to highest marginal value
            spin_alloc = capacity_mw * min_spin_fraction
            energy = capacity_mw - spin_alloc
            if sp > ep * 0.5:   # Reserve worth > 50% of energy price
                spin_alloc = capacity_mw * 0.3
                energy = capacity_mw - spin_alloc
            results.append((energy, spin_alloc))
        return results
