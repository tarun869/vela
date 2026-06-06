"""
Locational Marginal Price (LMP) engine for VPP dispatch optimization.

Computes real-time and day-ahead LMPs incorporating energy, congestion,
and marginal loss components at each bus in the network.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class LMPComponents:
    bus_id: int
    lmp: float             # Total LMP = energy + congestion + loss
    energy_component: float
    congestion_component: float
    loss_component: float
    interval: str


@dataclass
class LMPForecast:
    bus_id: int
    hourly_lmps: List[float]   # 24-hour or 48-hour forecast
    p10: List[float]            # 10th percentile
    p90: List[float]            # 90th percentile
    mean_lmp: float
    peak_lmp: float
    off_peak_lmp: float


class LMPEngine:
    """
    Computes and forecasts nodal LMPs for VPP optimization.

    Uses DC optimal power flow marginal costs + PTDF-based
    congestion pricing to decompose LMP into components.
    """

    def __init__(self, base_lambda: float = 35.0) -> None:
        """
        Args:
            base_lambda: System lambda (unconstrained energy clearing price).
        """
        self.base_lambda = base_lambda

    def compute_lmp(
        self,
        bus_id: int,
        system_lambda: float,
        ptdf_vector: np.ndarray,      # PTDF for this bus across all lines
        shadow_prices: np.ndarray,    # Shadow price for each binding constraint
        loss_factor: float = 0.02,    # Marginal loss factor
    ) -> LMPComponents:
        """
        Decompose LMP at a bus into energy, congestion, and loss components.

        LMP = system_lambda + PTDF^T * shadow_price + loss_factor * system_lambda
        """
        congestion = float(np.dot(ptdf_vector, shadow_prices))
        loss = loss_factor * system_lambda
        lmp = system_lambda + congestion + loss

        return LMPComponents(
            bus_id=bus_id,
            lmp=lmp,
            energy_component=system_lambda,
            congestion_component=congestion,
            loss_component=loss,
            interval="current",
        )

    def forecast_lmps(
        self,
        bus_id: int,
        historical_lmps: np.ndarray,   # Past N-hour LMPs for this bus
        forecast_hours: int = 24,
        include_uncertainty: bool = True,
    ) -> LMPForecast:
        """
        Forecast LMPs using historical pattern + mean reversion.

        Simple approach: use hourly seasonal pattern from history,
        add mean-reverting noise for probabilistic bands.
        """
        n = len(historical_lmps)
        if n < 24:
            base = np.full(forecast_hours, self.base_lambda)
        else:
            # Use same time-of-day pattern from last 7 days
            pattern = np.mean(historical_lmps[-168:].reshape(-1, 24), axis=0) if n >= 168 \
                else np.mean(historical_lmps.reshape(-1, min(24, n)), axis=0)
            base = np.tile(pattern[:forecast_hours], (forecast_hours // len(pattern) + 1))[:forecast_hours]

        mean_lmp = float(np.mean(base))
        hourly = base.tolist()
        if include_uncertainty:
            vol = float(np.std(historical_lmps)) if n > 1 else 5.0
            p10 = (base - 1.28 * vol).tolist()
            p90 = (base + 1.28 * vol).tolist()
        else:
            p10 = hourly
            p90 = hourly

        return LMPForecast(
            bus_id=bus_id,
            hourly_lmps=hourly,
            p10=p10, p90=p90,
            mean_lmp=mean_lmp,
            peak_lmp=float(np.max(base)),
            off_peak_lmp=float(np.min(base)),
        )

    def arbitrage_value(
        self,
        lmp_forecast: List[float],
        capacity_mw: float,
        efficiency_rt: float = 0.88,
        cycles_available: int = 1,
    ) -> float:
        """
        Estimate expected energy arbitrage revenue from LMP forecast.

        Greedy: charge in lowest-price hours, discharge in highest-price hours.
        """
        prices = sorted(enumerate(lmp_forecast), key=lambda x: x[1])
        sorted_prices = [p for _, p in prices]
        n = len(sorted_prices) // 2
        avg_buy = np.mean(sorted_prices[:n]) if n > 0 else 0.0
        avg_sell = np.mean(sorted_prices[-n:]) if n > 0 else 0.0
        spread = avg_sell - avg_buy * (1 / efficiency_rt)
        return max(0.0, spread * capacity_mw * cycles_available)
