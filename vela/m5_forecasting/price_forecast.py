"""LMP price forecasting using time-series models."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import NamedTuple


class PriceForecast(NamedTuple):
    timestamps: list[datetime]
    mean: list[float]
    p10: list[float]
    p90: list[float]
    model: str


@dataclass
class ARPriceModel:
    """Simple autoregressive model for LMP forecasting."""
    lags: int = 24
    _coeffs: np.ndarray = field(default=None, init=False, repr=False)
    _intercept: float = field(default=0.0, init=False, repr=False)
    _fitted: bool = field(default=False, init=False, repr=False)

    def fit(self, prices: list[float]) -> None:
        y = np.array(prices[self.lags:])
        X = np.column_stack([prices[i:len(prices)-self.lags+i] for i in range(self.lags)])
        X = np.hstack([np.ones((len(X), 1)), X])
        result = np.linalg.lstsq(X, y, rcond=None)
        coeffs = result[0]
        self._intercept = float(coeffs[0])
        self._coeffs = coeffs[1:]
        self._fitted = True

    def predict(self, recent: list[float], horizon: int = 24) -> PriceForecast:
        assert self._fitted, "Model must be fitted before prediction"
        window = list(recent[-self.lags:])
        preds = []
        for _ in range(horizon):
            val = self._intercept + float(np.dot(self._coeffs, window[-self.lags:]))
            val = max(0.0, val)
            preds.append(val)
            window.append(val)
        now = datetime.now(timezone.utc)
        ts = [now + timedelta(hours=i+1) for i in range(horizon)]
        std_dev = np.std(preds) * 0.15
        return PriceForecast(
            timestamps=ts,
            mean=preds,
            p10=[max(0, p - 1.28 * std_dev) for p in preds],
            p90=[p + 1.28 * std_dev for p in preds],
            model="AR",
        )
