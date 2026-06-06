"""
Liquidity risk management for VPP operations.

Covers margin call forecasting, credit facility management, working
capital projections, and stress testing of liquidity under adverse scenarios.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import numpy as np


@dataclass
class CashFlow:
    period: str
    energy_revenue_usd: float
    capacity_revenue_usd: float
    fuel_cost_usd: float
    om_cost_usd: float
    margin_calls_usd: float = 0.0
    collateral_posted_usd: float = 0.0

    @property
    def net_cash_usd(self) -> float:
        return (self.energy_revenue_usd + self.capacity_revenue_usd
                - self.fuel_cost_usd - self.om_cost_usd
                - self.margin_calls_usd - self.collateral_posted_usd)


@dataclass
class LiquidityReport:
    current_cash_usd: float
    forecast_cash_usd: List[float]    # Daily for next 30 days
    minimum_cash_usd: float
    days_to_liquidity_event: Optional[int]
    credit_headroom_usd: float
    liquidity_coverage_ratio: float   # LCR = liquid assets / 30-day stressed outflows


class LiquidityRiskEngine:
    """
    Forecasts liquidity under base case and stressed scenarios.
    """

    def __init__(
        self,
        initial_cash_usd: float,
        credit_facility_usd: float = 5_000_000.0,
        min_cash_buffer_usd: float = 500_000.0,
    ) -> None:
        self.cash = initial_cash_usd
        self.credit_facility = credit_facility_usd
        self.min_buffer = min_cash_buffer_usd

    def forecast_cash(
        self,
        cash_flows: List[CashFlow],
        price_shock_pct: float = 0.0,
    ) -> List[float]:
        """
        Forecast daily cash position applying an optional price shock.

        Price shock reduces energy revenue proportionally.
        """
        balance = self.cash
        forecast: List[float] = [balance]
        for cf in cash_flows:
            net = cf.net_cash_usd * (1.0 + price_shock_pct)
            balance += net
            forecast.append(balance)
        return forecast

    def assess(self, cash_flows: List[CashFlow]) -> LiquidityReport:
        """Run liquidity assessment under base and stressed scenarios."""
        base_forecast = self.forecast_cash(cash_flows)
        stressed_forecast = self.forecast_cash(cash_flows, price_shock_pct=-0.30)

        days_to_event: Optional[int] = None
        for i, bal in enumerate(stressed_forecast):
            if bal < self.min_buffer:
                days_to_event = i
                break

        total_stressed_outflows = sum(
            abs(min(0.0, cf.net_cash_usd * 0.70)) for cf in cash_flows[:30]
        )
        liquid_assets = self.cash + self.credit_facility
        lcr = liquid_assets / max(total_stressed_outflows, 1.0)

        return LiquidityReport(
            current_cash_usd=self.cash,
            forecast_cash_usd=base_forecast,
            minimum_cash_usd=float(min(base_forecast)),
            days_to_liquidity_event=days_to_event,
            credit_headroom_usd=self.credit_facility,
            liquidity_coverage_ratio=lcr,
        )

    def margin_call_forecast(
        self,
        position_mwh: float,
        price_vol_usd_mwh: float,
        confidence: float = 0.99,
    ) -> float:
        """Estimate potential margin call size (IM + VM combined)."""
        z = 2.326   # 99th percentile
        initial_margin = z * price_vol_usd_mwh * abs(position_mwh)
        return initial_margin
