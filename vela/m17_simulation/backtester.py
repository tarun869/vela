"""
Historical backtesting engine for VPP dispatch strategies.

Replays historical price, load, and renewable data against a dispatch
strategy to evaluate performance metrics: revenue, cycle count, P&L.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
import numpy as np


@dataclass
class BacktestData:
    timestamps: List[str]
    prices_usd_mwh: List[float]
    load_kw: List[float]
    solar_kw: List[float]
    wind_kw: List[float]
    regulation_price_usd_mw: Optional[List[float]] = None
    spinning_reserve_price: Optional[List[float]] = None
    dt_h: float = 1.0


@dataclass
class BacktestResult:
    strategy_name: str
    total_revenue_usd: float
    total_energy_dispatched_kwh: float
    total_cycles: float               # Full equivalent cycles
    avg_revenue_per_cycle_usd: float
    revenue_series: List[float]       # Period-by-period
    dispatch_series: List[float]      # kW per period
    soc_series: List[float]           # kWh per period
    sharpe_ratio: float
    max_drawdown_pct: float
    capacity_factor: float
    periods: int


DispatchFn = Callable[[float, float, float, float, float, float], float]
# (price, soc_kw, capacity_kwh, load_kw, solar_kw, wind_kw) -> dispatch_kw


class Backtester:
    """
    Historical backtest engine with configurable dispatch strategies.

    The dispatch function receives market/system state and returns
    a dispatch command (positive = discharging, negative = charging).
    """

    def __init__(
        self,
        capacity_kw: float,
        energy_capacity_kwh: float,
        initial_soc_kwh: float,
        charge_efficiency: float = 0.95,
        discharge_efficiency: float = 0.95,
        min_soc_kwh: float = None,
        max_soc_kwh: float = None,
    ) -> None:
        self.capacity_kw = capacity_kw
        self.energy_capacity_kwh = energy_capacity_kwh
        self.initial_soc_kwh = initial_soc_kwh
        self.charge_eff = charge_efficiency
        self.discharge_eff = discharge_efficiency
        self.min_soc = min_soc_kwh if min_soc_kwh is not None else energy_capacity_kwh * 0.05
        self.max_soc = max_soc_kwh if max_soc_kwh is not None else energy_capacity_kwh * 0.95

    def run(
        self,
        data: BacktestData,
        strategy_fn: DispatchFn,
        strategy_name: str = "custom",
    ) -> BacktestResult:
        """
        Run backtest with a dispatch strategy function.

        Returns:
            BacktestResult with performance metrics.
        """
        n = len(data.timestamps)
        dt = data.dt_h
        soc = self.initial_soc_kwh

        revenue_series: List[float] = []
        dispatch_series: List[float] = []
        soc_series: List[float] = []
        total_charge_kwh = 0.0
        total_discharge_kwh = 0.0

        for t in range(n):
            price = data.prices_usd_mwh[t] / 1000.0  # Convert to $/kWh
            load = data.load_kw[t]
            solar = data.solar_kw[t]
            wind = data.wind_kw[t]

            # Get dispatch signal
            raw_dispatch = strategy_fn(
                price, soc, self.energy_capacity_kwh, load, solar, wind
            )

            # Enforce capacity and SOC constraints
            if raw_dispatch > 0:  # Discharging
                max_discharge = min(
                    self.capacity_kw,
                    (soc - self.min_soc) / dt * self.discharge_eff
                )
                dispatch_kw = min(raw_dispatch, max_discharge)
                energy_change = -dispatch_kw * dt / self.discharge_eff
            else:  # Charging
                max_charge = min(
                    self.capacity_kw,
                    (self.max_soc - soc) / dt / self.charge_eff
                )
                dispatch_kw = max(raw_dispatch, -max_charge)
                energy_change = -dispatch_kw * dt * self.charge_eff

            soc = max(self.min_soc, min(self.max_soc, soc + energy_change))
            revenue = dispatch_kw * price * dt

            if dispatch_kw > 0:
                total_discharge_kwh += dispatch_kw * dt
            else:
                total_charge_kwh += abs(dispatch_kw) * dt

            revenue_series.append(revenue)
            dispatch_series.append(dispatch_kw)
            soc_series.append(soc)

        total_revenue = sum(revenue_series)
        total_cycles = min(total_charge_kwh, total_discharge_kwh) / self.energy_capacity_kwh
        total_energy = total_discharge_kwh

        # Risk metrics
        rev_array = np.array(revenue_series)
        sharpe = self._sharpe(rev_array)
        drawdown = self._max_drawdown(np.cumsum(rev_array))
        cap_factor = np.mean(np.abs(dispatch_series)) / self.capacity_kw if self.capacity_kw > 0 else 0.0

        return BacktestResult(
            strategy_name=strategy_name,
            total_revenue_usd=total_revenue,
            total_energy_dispatched_kwh=total_energy,
            total_cycles=total_cycles,
            avg_revenue_per_cycle_usd=total_revenue / max(total_cycles, 0.01),
            revenue_series=revenue_series,
            dispatch_series=dispatch_series,
            soc_series=soc_series,
            sharpe_ratio=sharpe,
            max_drawdown_pct=drawdown * 100.0,
            capacity_factor=float(cap_factor),
            periods=n,
        )

    def compare_strategies(
        self,
        data: BacktestData,
        strategies: Dict[str, DispatchFn],
    ) -> Dict[str, BacktestResult]:
        """Run multiple strategies and return comparative results."""
        return {name: self.run(data, fn, name) for name, fn in strategies.items()}

    @staticmethod
    def _sharpe(returns: np.ndarray, rf: float = 0.0) -> float:
        if returns.std() == 0:
            return 0.0
        return float((returns.mean() - rf) / returns.std() * np.sqrt(len(returns)))

    @staticmethod
    def _max_drawdown(equity: np.ndarray) -> float:
        if len(equity) < 2:
            return 0.0
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / np.where(peak != 0, np.abs(peak), 1.0)
        return float(-dd.min())


def price_threshold_strategy(
    threshold_usd_kwh: float = 0.05,
) -> DispatchFn:
    """Factory: dispatch when price > threshold, charge otherwise."""
    def fn(price, soc, cap_kwh, load, solar, wind) -> float:
        if price > threshold_usd_kwh:
            return cap_kwh * 0.5  # Discharge at 50% capacity
        else:
            return -cap_kwh * 0.3  # Charge at 30% capacity
    return fn


def arbitrage_strategy(
    low_threshold: float = 0.03,
    high_threshold: float = 0.07,
) -> DispatchFn:
    """Factory: charge at low prices, discharge at high prices."""
    def fn(price, soc, cap_kwh, load, solar, wind) -> float:
        soc_pct = soc / max(cap_kwh, 1.0)
        if price < low_threshold and soc_pct < 0.80:
            return -cap_kwh * 0.5
        elif price > high_threshold and soc_pct > 0.20:
            return cap_kwh * 0.8
        return 0.0
    return fn
