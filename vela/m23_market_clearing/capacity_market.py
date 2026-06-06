"""
Capacity market modeling for VPP participation.

Models forward capacity auctions (PJM RPM, ISO-NE FCA, MISO LRPPA)
where resources commit to availability in future delivery years.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class CapacityOffer:
    resource_id: str
    qualified_capacity_mw: float   # ICAP or UCAP after availability derating
    offer_price_usd_mw_day: float
    resource_type: str              # "generator", "dr", "storage", "import"
    zone: str
    intermittent: bool = False
    demand_response: bool = False


@dataclass
class CapacityMarketResult:
    clearing_price_usd_mw_day: float
    total_capacity_cleared_mw: float
    procured_offers: List[str]       # resource_ids
    reliability_target_met: bool
    annual_revenue_per_mw_usd: float
    consumer_cost_usd_year: float


@dataclass
class ReliabilityRequirement:
    zone: str
    installed_reserve_margin: float   # e.g., 0.165 for 16.5%
    load_mw: float
    existing_capacity_mw: float

    @property
    def required_capacity_mw(self) -> float:
        return self.load_mw * (1 + self.installed_reserve_margin)

    @property
    def net_capacity_requirement_mw(self) -> float:
        return max(0.0, self.required_capacity_mw - self.existing_capacity_mw)


class CapacityMarketAuction:
    """
    Simulates forward capacity market auction with variable resource requirement (VRR) curve.

    The VRR curve defines how much capacity is needed and at what prices,
    implementing a downward-sloping demand curve for capacity.
    """

    def __init__(
        self,
        requirement: ReliabilityRequirement,
        net_cone: float = 90_000.0,  # Net Cost of New Entry $/MW-year
    ) -> None:
        self.req = requirement
        self.net_cone = net_cone

    def vrr_demand_curve(self, capacity_mw: float) -> float:
        """
        PJM-style Variable Resource Requirement (VRR) demand curve.

        Returns clearing price at given capacity level.
        Linearly interpolated between key capacity/price points.
        """
        cap_req = self.req.required_capacity_mw
        if capacity_mw <= cap_req * 0.95:
            return self.net_cone   # Price cap at Net CONE
        elif capacity_mw <= cap_req:
            t = (capacity_mw - cap_req * 0.95) / (cap_req * 0.05)
            return self.net_cone * (1 - 0.4 * t)
        elif capacity_mw <= cap_req * 1.05:
            t = (capacity_mw - cap_req) / (cap_req * 0.05)
            return self.net_cone * 0.6 * (1 - t)
        else:
            return 0.0    # Excess capacity: price = 0

    def clear(self, offers: List[CapacityOffer]) -> CapacityMarketResult:
        """Clear capacity auction against VRR demand curve."""
        sorted_offers = sorted(offers, key=lambda o: o.offer_price_usd_mw_day)
        cumulative_cap = 0.0
        clearing_price_day = 0.0
        procured: List[str] = []

        for offer in sorted_offers:
            cumulative_cap += offer.qualified_capacity_mw
            demand_price = self.vrr_demand_curve(cumulative_cap) / 365.0  # $/MW-day
            if offer.offer_price_usd_mw_day <= demand_price:
                procured.append(offer.resource_id)
                clearing_price_day = max(clearing_price_day, offer.offer_price_usd_mw_day)
            else:
                break

        clearing_price_year = clearing_price_day * 365
        reliability_met = cumulative_cap >= self.req.required_capacity_mw

        return CapacityMarketResult(
            clearing_price_usd_mw_day=clearing_price_day,
            total_capacity_cleared_mw=cumulative_cap,
            procured_offers=procured,
            reliability_target_met=reliability_met,
            annual_revenue_per_mw_usd=clearing_price_year,
            consumer_cost_usd_year=cumulative_cap * clearing_price_year,
        )
