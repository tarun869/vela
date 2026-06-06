"""
Financial Transmission Rights (FTR/CRR) valuation and hedging.

FTRs are financial instruments that allow market participants to
hedge against transmission congestion costs in nodal markets.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class FTR:
    ftr_id: str
    holder_id: str
    injection_node: int
    withdrawal_node: int
    mw_amount: float
    ftr_type: str         # "obligation", "option"
    direction: str        # "forward", "counter"
    period_hours: int
    auction_cost_usd: float


@dataclass
class FTRValuationResult:
    ftr_id: str
    realized_value_usd: float
    congestion_hedged_usd: float
    net_position_usd: float
    irr: float


class FTRValuator:
    """
    Values FTR positions based on realized nodal price spreads.
    """

    def __init__(self) -> None:
        self._ftrs: Dict[str, FTR] = {}

    def register(self, ftr: FTR) -> None:
        self._ftrs[ftr.ftr_id] = ftr

    def value_ftr(
        self,
        ftr_id: str,
        hourly_lmps: Dict[int, List[float]],   # bus_id -> list of hourly LMPs
    ) -> FTRValuationResult:
        """
        Compute FTR settlement value from hourly LMP spreads.

        Settlement value = sum over hours of (LMP_withdrawal - LMP_injection) * MW
        For options: only positive congestion revenue is collected.
        """
        ftr = self._ftrs[ftr_id]
        inj_lmps = hourly_lmps.get(ftr.injection_node, [0.0] * ftr.period_hours)
        wth_lmps = hourly_lmps.get(ftr.withdrawal_node, [0.0] * ftr.period_hours)

        realized_value = 0.0
        for inj_p, wth_p in zip(inj_lmps, wth_lmps):
            spread = (wth_p - inj_p) * ftr.mw_amount
            if ftr.ftr_type == "option":
                realized_value += max(0.0, spread)
            else:
                realized_value += spread

        net = realized_value - ftr.auction_cost_usd
        irr = net / max(ftr.auction_cost_usd, 1.0)

        return FTRValuationResult(
            ftr_id=ftr_id,
            realized_value_usd=realized_value,
            congestion_hedged_usd=realized_value,
            net_position_usd=net,
            irr=irr,
        )

    def portfolio_summary(
        self, hourly_lmps: Dict[int, List[float]]
    ) -> Dict[str, float]:
        """Summarize FTR portfolio performance."""
        total_realized = 0.0
        total_cost = 0.0
        for ftr_id, ftr in self._ftrs.items():
            result = self.value_ftr(ftr_id, hourly_lmps)
            total_realized += result.realized_value_usd
            total_cost += ftr.auction_cost_usd
        return {
            "total_realized_usd": total_realized,
            "total_auction_cost_usd": total_cost,
            "net_position_usd": total_realized - total_cost,
            "portfolio_irr": (total_realized - total_cost) / max(total_cost, 1.0),
        }
