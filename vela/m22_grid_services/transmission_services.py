"""
Transmission services modeling for VPP grid support.

Covers transmission constraint management, congestion revenue rights,
and VPP participation in transmission planning processes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class TransmissionConstraint:
    constraint_id: str
    from_bus: int
    to_bus: int
    limit_mw: float
    current_flow_mw: float
    shadow_price_usd_mwh: float   # LMP spread due to congestion
    binding: bool

    @property
    def loading_pct(self) -> float:
        return abs(self.current_flow_mw) / max(self.limit_mw, 1.0) * 100.0


@dataclass
class CongestionRevenueRight:
    crr_id: str
    holder_id: str
    injection_node: int
    withdrawal_node: int
    mw_award: float
    period: str
    crr_type: str           # "obligation", "option"
    auction_price_usd: float


class TransmissionService:
    """
    Models VPP participation in transmission constraint management
    and congestion revenue right markets.
    """

    def __init__(self) -> None:
        self._constraints: Dict[str, TransmissionConstraint] = {}
        self._crrs: Dict[str, CongestionRevenueRight] = {}

    def add_constraint(self, constraint: TransmissionConstraint) -> None:
        self._constraints[constraint.constraint_id] = constraint

    def binding_constraints(self) -> List[TransmissionConstraint]:
        return [c for c in self._constraints.values() if c.binding]

    def congestion_revenue(
        self,
        injection_node: int,
        withdrawal_node: int,
        scheduled_mw: float,
    ) -> float:
        """
        Compute expected congestion revenue for a bilateral schedule.

        Revenue = sum of (shadow_price * PTDF * scheduled_mw) for binding constraints.
        """
        # Simplified: use shadow price of any binding constraint between nodes
        revenue = 0.0
        for c in self.binding_constraints():
            if c.from_bus == injection_node or c.to_bus == withdrawal_node:
                ptdf = 0.3   # Simplified PTDF
                revenue += c.shadow_price_usd_mwh * ptdf * scheduled_mw
        return revenue

    def crr_value(self, crr: CongestionRevenueRight, shadow_prices: Dict[Tuple, float]) -> float:
        """Compute realized CRR value given shadow prices."""
        key = (crr.injection_node, crr.withdrawal_node)
        spread = shadow_prices.get(key, 0.0)
        if crr.crr_type == "option":
            return max(0.0, spread * crr.mw_award)  # Options: pay positive congestion only
        else:
            return spread * crr.mw_award  # Obligations: pay both ways

    def virtual_transmission_cost(
        self,
        from_node: int,
        to_node: int,
        energy_mwh: float,
        lmp_from: float,
        lmp_to: float,
    ) -> Dict[str, float]:
        """
        Compute transmission cost for energy movement between nodes.
        """
        energy_charge = abs(lmp_to - lmp_from) * energy_mwh
        wheeling_charge = 2.0 * energy_mwh   # Simplified $/MWh wheeling rate
        return {
            "energy_charge_usd": energy_charge,
            "wheeling_charge_usd": wheeling_charge,
            "total_usd": energy_charge + wheeling_charge,
            "net_congestion_usd": (lmp_to - lmp_from) * energy_mwh,
        }
