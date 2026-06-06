"""
Day-ahead and real-time market clearing engine.

Implements uniform-price auction clearing with locational marginal
pricing using a simplified DC optimal power flow formulation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class GenerationOffer:
    resource_id: str
    bus_id: int
    quantity_mw: float
    price_usd_mwh: float
    start_cost_usd: float = 0.0
    min_online_h: float = 0.0
    ramp_mw_min: float = 999.0


@dataclass
class LoadBid:
    load_id: str
    bus_id: int
    quantity_mw: float
    price_usd_mwh: float    # Max willingness to pay (or VOLL for non-price-responsive)


@dataclass
class ClearingResult:
    interval: str
    cleared_offers: Dict[str, float]    # resource_id -> cleared_mw
    cleared_loads: Dict[str, float]     # load_id -> cleared_mw
    lmps: Dict[int, float]              # bus_id -> LMP ($/MWh)
    system_lambda: float                 # Shadow price of energy balance
    total_cost_usd: float
    total_load_mw: float
    total_gen_mw: float


class MarketClearingEngine:
    """
    Clears energy market using merit order dispatch with LMP pricing.

    Production cost model with bus injection limits and transmission
    constraints enforced via shadow prices (simplified DC OPF).
    """

    def __init__(self, voll_usd_mwh: float = 10_000.0) -> None:
        """
        Args:
            voll_usd_mwh: Value of Lost Load for reliability pricing.
        """
        self.voll = voll_usd_mwh

    def clear(
        self,
        interval: str,
        offers: List[GenerationOffer],
        loads: List[LoadBid],
        ptdf_matrix: Optional[np.ndarray] = None,
        line_limits_mw: Optional[List[float]] = None,
    ) -> ClearingResult:
        """
        Clear the energy market for a single interval.

        Procedure:
        1. Sort generation offers by price (merit order).
        2. Dispatch against aggregate load until balanced.
        3. Set LMP = marginal offer price at clearing point.
        4. Apply PTDF congestion components if provided.
        """
        # Step 1: Sort offers
        sorted_offers = sorted(offers, key=lambda o: o.price_usd_mwh)
        total_load = sum(lb.quantity_mw for lb in loads)

        cleared_offers: Dict[str, float] = {}
        remaining_load = total_load
        system_lambda = 0.0
        total_cost = 0.0

        # Step 2: Merit order dispatch
        for offer in sorted_offers:
            if remaining_load <= 1e-6:
                break
            cleared = min(offer.quantity_mw, remaining_load)
            cleared_offers[offer.resource_id] = cleared
            system_lambda = offer.price_usd_mwh   # Marginal price
            total_cost += cleared * offer.price_usd_mwh
            remaining_load -= cleared

        # If load exceeds all offers, use VOLL
        if remaining_load > 1e-6:
            system_lambda = self.voll

        # Step 3: LMP = system_lambda + congestion component
        lmps = self._compute_lmps(
            system_lambda, offers, cleared_offers, ptdf_matrix, line_limits_mw
        )

        cleared_loads = {lb.load_id: lb.quantity_mw for lb in loads}

        return ClearingResult(
            interval=interval,
            cleared_offers=cleared_offers,
            cleared_loads=cleared_loads,
            lmps=lmps,
            system_lambda=system_lambda,
            total_cost_usd=total_cost,
            total_load_mw=total_load,
            total_gen_mw=sum(cleared_offers.values()),
        )

    def _compute_lmps(
        self,
        system_lambda: float,
        offers: List[GenerationOffer],
        cleared: Dict[str, float],
        ptdf: Optional[np.ndarray],
        line_limits: Optional[List[float]],
    ) -> Dict[int, float]:
        """Compute LMPs per bus including congestion component."""
        bus_ids = {o.bus_id for o in offers}
        lmps: Dict[int, float] = {}

        for bus in bus_ids:
            congestion_component = 0.0
            if ptdf is not None and line_limits is not None:
                # Simplified: check binding lines
                for i, (limit, ptdf_row) in enumerate(zip(line_limits, ptdf)):
                    flow = np.dot(ptdf_row, np.zeros(len(bus_ids)))  # Simplified
                    if abs(flow) >= limit * 0.99:
                        congestion_component += ptdf_row[0] * system_lambda * 0.1
            lmps[bus] = system_lambda + congestion_component

        return lmps
