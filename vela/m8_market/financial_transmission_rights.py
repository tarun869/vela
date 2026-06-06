"""Financial Transmission Rights (FTR) and Congestion Revenue Rights (CRR) modeling."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple


class FTRPosition(NamedTuple):
    ftr_id: str
    source_node: str          # Injection node
    sink_node: str            # Withdrawal node
    mw: float                 # MW of rights (positive = source->sink)
    direction: str            # "OBLIGATION" or "OPTION"
    delivery_period: str      # e.g., "2025-Q3"
    purchase_price: float     # $ paid at auction
    hedge_value: float        # $ hedged against congestion
    pnl: float                # Realized P&L


@dataclass
class FTRValuation:
    """
    FTR/CRR valuation and hedging analysis.

    FTRs hedge against congestion costs between two nodes.
    Revenue = (LMP_sink - LMP_source) * MW * hours

    For a VPP operator with assets at multiple nodes:
    - Long FTR: benefits when sink > source
    - Short FTR: benefits when source > sink
    """

    def value_ftr(
        self,
        source_lmp: list[float],
        sink_lmp: list[float],
        mw: float,
        dt_hours: float = 1.0,
        direction: str = "OBLIGATION",
    ) -> float:
        """
        Compute FTR revenue for a given LMP history.

        FTR Obligation: revenue = (LMP_sink - LMP_source) * MW * dt (can be negative)
        FTR Option: revenue = max(0, LMP_sink - LMP_source) * MW * dt
        """
        src = np.array(source_lmp)
        snk = np.array(sink_lmp)
        congestion = snk - src

        if direction == "OBLIGATION":
            revenue = float(np.sum(congestion * mw * dt_hours))
        else:  # OPTION
            revenue = float(np.sum(np.maximum(0, congestion) * mw * dt_hours))
        return revenue

    def hedge_ratio(
        self,
        asset_load_mw: list[float],
        lmp_source: list[float],
        lmp_sink: list[float],
    ) -> dict[str, float]:
        """
        Determine optimal FTR hedge ratio to minimize congestion cost variance.

        Uses OLS regression: total_cost ~ alpha + beta * congestion_spread
        """
        congestion = np.array(lmp_sink) - np.array(lmp_source)
        load = np.array(asset_load_mw)

        # Congestion cost without hedge
        total_cost = load * np.array(lmp_sink)
        cov_matrix = np.cov(congestion, total_cost)
        var_congestion = float(cov_matrix[0, 0])
        cov_cost_congestion = float(cov_matrix[0, 1])

        # Optimal hedge: minimizes variance of hedged cost
        if abs(var_congestion) > 1e-6:
            optimal_mw = cov_cost_congestion / var_congestion
        else:
            optimal_mw = 0.0

        unhedged_var = float(np.var(total_cost))
        hedged_cost = total_cost - optimal_mw * congestion
        hedged_var = float(np.var(hedged_cost))

        return {
            "optimal_ftr_mw": optimal_mw,
            "unhedged_cost_std": float(np.sqrt(unhedged_var)),
            "hedged_cost_std": float(np.sqrt(hedged_var)),
            "variance_reduction_pct": (1 - hedged_var / (unhedged_var + 1e-6)) * 100,
            "avg_congestion_spread": float(np.mean(congestion)),
        }

    def ftr_auction_bid(
        self,
        source_node: str,
        sink_node: str,
        forecast_congestion: list[float],
        uncertainty_sigma: float = 5.0,
        mw_increment: float = 1.0,
        max_mw: float = 50.0,
        risk_aversion: float = 0.5,
    ) -> dict[str, float]:
        """
        Compute optimal FTR auction bid using expected value minus risk premium.

        Bid price = E[congestion] - risk_aversion * sigma(congestion)

        Parameters
        ----------
        forecast_congestion : list[float]
            Hourly LMP_sink - LMP_source forecast for delivery period
        uncertainty_sigma : float
            Standard deviation of congestion forecast error
        """
        expected_congestion = float(np.mean(forecast_congestion))
        total_hours = len(forecast_congestion)

        # Expected value per MW
        ev_per_mw = expected_congestion * total_hours

        # Risk premium (penalize uncertainty)
        risk_premium = risk_aversion * uncertainty_sigma * np.sqrt(total_hours)

        bid_price = max(0.0, ev_per_mw - risk_premium)

        # Optimal MW: invest up to the point where marginal EV = market clearing price
        # Simplified: linear demand curve assumption
        optimal_mw = min(max_mw, max(0, mw_increment * int(ev_per_mw / (risk_premium + 1))))

        return {
            "source": source_node,
            "sink": sink_node,
            "expected_congestion_mwh": ev_per_mw,
            "bid_price_per_mw": bid_price,
            "optimal_mw": optimal_mw,
            "expected_revenue": optimal_mw * bid_price,
        }

    def historical_pnl_analysis(
        self,
        positions: list[FTRPosition],
    ) -> dict[str, float]:
        """Analyze realized P&L of FTR positions."""
        if not positions:
            return {}
        pnls = np.array([p.pnl for p in positions])
        purchase_costs = np.array([p.purchase_price for p in positions])
        hedge_values = np.array([p.hedge_value for p in positions])
        net_pnl = pnls - purchase_costs

        return {
            "total_pnl": float(np.sum(net_pnl)),
            "avg_pnl_per_position": float(np.mean(net_pnl)),
            "win_rate": float(np.mean(net_pnl > 0)),
            "total_hedge_value": float(np.sum(hedge_values)),
            "net_hedge_efficiency": float(np.sum(hedge_values) / (np.sum(purchase_costs) + 1e-6)),
        }
