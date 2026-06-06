"""LMP price spike detection model for real-time alert generation."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import NamedTuple


class SpikeAlert(NamedTuple):
    timestamp: datetime
    price: float
    threshold: float
    severity: str        # "moderate", "high", "extreme"
    z_score: float
    rolling_mean: float
    rolling_std: float
    recommended_action: str


@dataclass
class PriceSpikeDetector:
    """
    Real-time LMP price spike detection using rolling z-score and adaptive thresholds.

    Detects spikes using:
    1. Rolling z-score (deviation from recent mean)
    2. Absolute price threshold crossings
    3. Rate-of-change (sudden jumps)

    Typical ERCOT price spikes can reach $9,000/MWh during scarcity events.
    """
    window_hours: int = 72           # Rolling window for baseline statistics
    z_threshold_moderate: float = 2.0
    z_threshold_high: float = 3.5
    z_threshold_extreme: float = 6.0
    abs_threshold_moderate: float = 150.0   # $/MWh
    abs_threshold_extreme: float = 1000.0   # $/MWh
    roc_threshold: float = 50.0             # $/MWh/interval sudden jump
    _price_history: list[float] = field(default_factory=list, init=False, repr=False)
    _ts_history: list[datetime] = field(default_factory=list, init=False, repr=False)

    def update(self, timestamp: datetime, price: float) -> SpikeAlert | None:
        """
        Ingest a new price observation.  Returns SpikeAlert if spike detected.
        """
        self._price_history.append(price)
        self._ts_history.append(timestamp)

        # Trim to rolling window
        cutoff = timestamp - timedelta(hours=self.window_hours)
        while self._ts_history and self._ts_history[0] < cutoff:
            self._ts_history.pop(0)
            self._price_history.pop(0)

        if len(self._price_history) < 4:
            return None  # Not enough history

        arr = np.array(self._price_history)
        roll_mean = float(np.mean(arr[:-1]))
        roll_std = float(np.std(arr[:-1])) + 1e-6
        z = (price - roll_mean) / roll_std

        # Rate of change
        roc = abs(price - self._price_history[-2]) if len(self._price_history) >= 2 else 0.0

        severity = None
        if z >= self.z_threshold_extreme or price >= self.abs_threshold_extreme:
            severity = "extreme"
        elif z >= self.z_threshold_high or price >= self.abs_threshold_moderate * 3:
            severity = "high"
        elif z >= self.z_threshold_moderate or price >= self.abs_threshold_moderate or roc >= self.roc_threshold:
            severity = "moderate"

        if severity is None:
            return None

        action_map = {
            "moderate": "Consider discharging storage if SOC > 50%",
            "high": "Dispatch all available storage immediately; defer charging",
            "extreme": "Maximum discharge; activate all DR resources; hedge exposure",
        }

        return SpikeAlert(
            timestamp=timestamp,
            price=price,
            threshold=roll_mean + self.z_threshold_moderate * roll_std,
            severity=severity,
            z_score=z,
            rolling_mean=roll_mean,
            rolling_std=roll_std,
            recommended_action=action_map[severity],
        )

    def batch_detect(
        self,
        timestamps: list[datetime],
        prices: list[float],
    ) -> list[SpikeAlert]:
        """Run spike detection over a historical price series."""
        alerts = []
        for ts, p in zip(timestamps, prices):
            alert = self.update(ts, p)
            if alert is not None:
                alerts.append(alert)
        return alerts

    def rolling_stats(self) -> dict[str, float]:
        """Return current rolling window statistics."""
        if len(self._price_history) < 2:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "n": float(len(self._price_history))}
        arr = np.array(self._price_history)
        return {
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "p95": float(np.percentile(arr, 95)),
            "n": float(len(arr)),
        }

    def spike_probability(
        self,
        forecast_prices: list[float],
        spike_threshold: float = 200.0,
    ) -> list[float]:
        """
        Estimate spike probability for each forecasted price interval.

        Uses a logistic function centered on the spike threshold
        with width calibrated to historical volatility.
        """
        if len(self._price_history) < 2:
            vol = 20.0
        else:
            vol = float(np.std(self._price_history)) + 1e-6

        probs = []
        for p in forecast_prices:
            # Logistic probability P(actual > threshold | forecast = p)
            # Simplified: normal CDF upper tail
            z = (p - spike_threshold) / vol
            prob = 1 / (1 + np.exp(-z * 1.5))
            probs.append(float(prob))
        return probs


@dataclass
class VolatilityRegimeDetector:
    """
    Detects volatility regime changes in LMP prices.

    Uses EWMA variance to classify market into:
    - LOW: calm market, normal dispatch
    - ELEVATED: higher uncertainty, reduce position sizes
    - STRESSED: extreme volatility, prioritize risk management
    """
    ewma_decay: float = 0.94  # RiskMetrics-style decay
    _ewma_var: float = field(default=100.0, init=False, repr=False)  # initial variance
    _last_price: float = field(default=35.0, init=False, repr=False)

    def update(self, price: float) -> str:
        """Update EWMA variance and return current regime."""
        ret = price - self._last_price
        self._ewma_var = self.ewma_decay * self._ewma_var + (1 - self.ewma_decay) * ret ** 2
        self._last_price = price
        vol = float(self._ewma_var ** 0.5)
        if vol < 10:
            return "LOW"
        elif vol < 50:
            return "ELEVATED"
        else:
            return "STRESSED"

    @property
    def current_volatility(self) -> float:
        return float(self._ewma_var ** 0.5)
