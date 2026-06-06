"""
Market risk measurement for VPP energy trading positions.

Covers price risk, volume risk, shape risk, and basis risk
using standard financial risk measures adapted for power markets.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class MarketPosition:
    position_id: str
    resource_id: str
    quantity_mwh: float       # Positive = long (generator), negative = short (load)
    forward_price: float      # Contracted/hedged price $/MWh
    mark_to_market_price: float  # Current market price $/MWh

    @property
    def mtm_pnl(self) -> float:
        return (self.mark_to_market_price - self.forward_price) * self.quantity_mwh


@dataclass
class MarketRiskReport:
    total_positions_mwh: float
    net_long_mwh: float
    net_short_mwh: float
    total_mtm_usd: float
    var_95_usd: float
    var_99_usd: float
    expected_shortfall_usd: float
    basis_risk_usd: float
    price_volatility: float


class MarketRiskEngine:
    """
    Measures market risk exposure across VPP energy trading portfolio.

    Computes VaR using historical simulation (rolling price scenarios).
    """

    def __init__(self, lookback_days: int = 252) -> None:
        self.lookback_days = lookback_days

    def compute_risk(
        self,
        positions: List[MarketPosition],
        historical_prices: np.ndarray,   # shape (n_days, n_hubs)
    ) -> MarketRiskReport:
        """
        Compute market risk metrics from historical price simulation.

        Args:
            positions: Current energy positions.
            historical_prices: Daily price history per hub ($/MWh).
        """
        returns = np.diff(historical_prices, axis=0) / (historical_prices[:-1] + 1e-9)
        price_vol = float(np.std(returns[:, 0]) * np.sqrt(252))

        # P&L for each historical day as scenario
        net_qty = sum(p.quantity_mwh for p in positions)
        avg_price = np.mean(historical_prices[:, 0])
        pnl_scenarios = returns[:, 0] * avg_price * net_qty

        pnl_sorted = np.sort(pnl_scenarios)
        n = len(pnl_sorted)
        var_95 = float(-np.percentile(pnl_sorted, 5))
        var_99 = float(-np.percentile(pnl_sorted, 1))
        es = float(-np.mean(pnl_sorted[pnl_sorted <= np.percentile(pnl_sorted, 5)]))

        total_mtm = sum(p.mtm_pnl for p in positions)
        net_long = sum(p.quantity_mwh for p in positions if p.quantity_mwh > 0)
        net_short = sum(abs(p.quantity_mwh) for p in positions if p.quantity_mwh < 0)

        # Simplified basis risk: spread between hub and node prices
        basis_risk = abs(total_mtm) * 0.05  # Simplified 5% basis risk estimate

        return MarketRiskReport(
            total_positions_mwh=sum(abs(p.quantity_mwh) for p in positions),
            net_long_mwh=net_long,
            net_short_mwh=net_short,
            total_mtm_usd=total_mtm,
            var_95_usd=var_95,
            var_99_usd=var_99,
            expected_shortfall_usd=es,
            basis_risk_usd=basis_risk,
            price_volatility=price_vol,
        )

    def delta_hedge_ratio(
        self,
        position_mwh: float,
        futures_correlation: float = 0.95,
    ) -> float:
        """Compute optimal hedge ratio (minimum variance hedge)."""
        # h* = correlation * (sigma_spot / sigma_futures)
        # Simplified: assume equal volatilities, so h* = correlation
        return futures_correlation

    def stress_test(
        self,
        positions: List[MarketPosition],
        price_shocks: Dict[str, float],   # scenario_name -> price_change $/MWh
    ) -> Dict[str, float]:
        """Apply stress scenarios to portfolio."""
        results: Dict[str, float] = {}
        for scenario, shock in price_shocks.items():
            pnl = sum(shock * p.quantity_mwh for p in positions)
            results[scenario] = pnl
        return results
