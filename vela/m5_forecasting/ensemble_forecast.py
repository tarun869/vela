"""Ensemble forecast combining AR, GP, and load models with weighted averaging."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import NamedTuple, Protocol


class ForecastResult(NamedTuple):
    timestamps: list[datetime]
    mean: list[float]
    p10: list[float]
    p90: list[float]
    model: str


class BaseForecaster(Protocol):
    """Protocol for pluggable forecast models."""
    def predict(self, *args, **kwargs) -> ForecastResult: ...  # type: ignore[override]


@dataclass
class EnsembleForecast:
    """
    Weighted ensemble combining multiple price/load forecasters.

    Weights are learned via out-of-sample RMSE on a validation set,
    or can be set manually. Uses variance-weighted or simple average.
    """
    model_names: list[str] = field(default_factory=list)
    weights: np.ndarray = field(default=None, init=False, repr=False)
    _val_rmses: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def fit_weights(
        self,
        model_forecasts: dict[str, list[float]],
        actuals: list[float],
    ) -> None:
        """
        Compute inverse-RMSE weights from validation-set performance.

        Parameters
        ----------
        model_forecasts : dict[str, list[float]]
            Mapping of model name -> list of predicted values
        actuals : list[float]
            Observed ground truth
        """
        y = np.array(actuals)
        inv_rmses = {}
        for name, preds in model_forecasts.items():
            yhat = np.array(preds)
            rmse = float(np.sqrt(np.mean((y - yhat) ** 2)))
            self._val_rmses[name] = rmse
            inv_rmses[name] = 1.0 / (rmse + 1e-6)

        total = sum(inv_rmses.values())
        self.model_names = list(model_forecasts.keys())
        self.weights = np.array([inv_rmses[n] / total for n in self.model_names])

    def combine(
        self,
        model_forecasts: dict[str, list[float]],
        model_p10: dict[str, list[float]] | None = None,
        model_p90: dict[str, list[float]] | None = None,
        timestamps: list[datetime] | None = None,
    ) -> ForecastResult:
        """
        Combine forecasts using learned weights.

        Falls back to equal weighting if weights not fitted.
        """
        names = list(model_forecasts.keys())
        n_models = len(names)
        if self.weights is None or len(self.weights) != n_models:
            w = np.ones(n_models) / n_models
        else:
            # Re-align weights to current model list
            w = np.array([
                self.weights[self.model_names.index(n)] if n in self.model_names else 1.0 / n_models
                for n in names
            ])
            w /= w.sum()

        T = len(next(iter(model_forecasts.values())))
        means = np.zeros(T)
        for i, name in enumerate(names):
            means += w[i] * np.array(model_forecasts[name])

        # Ensemble uncertainty: weighted variance + inter-model disagreement
        if model_p10 and model_p90:
            lower = np.zeros(T)
            upper = np.zeros(T)
            for i, name in enumerate(names):
                if name in model_p10:
                    lower += w[i] * np.array(model_p10[name])
                    upper += w[i] * np.array(model_p90[name])
            # Add inter-model spread
            pred_matrix = np.array([model_forecasts[n] for n in names])
            inter_sigma = np.std(pred_matrix, axis=0)
            lower = np.maximum(0, lower - inter_sigma)
            upper = upper + inter_sigma
        else:
            pred_matrix = np.array([model_forecasts[n] for n in names])
            sigma = np.std(pred_matrix, axis=0) + np.std(means) * 0.1
            lower = np.maximum(0, means - 1.28 * sigma)
            upper = means + 1.28 * sigma

        if timestamps is None:
            now = datetime.now(timezone.utc)
            timestamps = [now + timedelta(hours=i) for i in range(T)]

        return ForecastResult(
            timestamps=timestamps,
            mean=means.tolist(),
            p10=lower.tolist(),
            p90=upper.tolist(),
            model=f"Ensemble({'+'.join(names)})",
        )

    def validation_summary(self) -> dict[str, float]:
        """Return per-model RMSE from validation fitting."""
        return dict(self._val_rmses)


@dataclass
class BootstrapEnsemble:
    """
    Bootstrap ensemble for uncertainty estimation.

    Trains multiple AR models on bootstrap samples of the training data
    and uses percentiles of predictions as confidence intervals.
    """
    n_bootstrap: int = 50
    lags: int = 24
    _boot_intercepts: list[float] = field(default_factory=list, init=False, repr=False)
    _boot_coeffs: list[np.ndarray] = field(default_factory=list, init=False, repr=False)

    def fit(self, prices: list[float]) -> None:
        """Fit bootstrap ensemble on price history."""
        rng = np.random.default_rng(42)
        n = len(prices)
        self._boot_intercepts.clear()
        self._boot_coeffs.clear()

        for _ in range(self.n_bootstrap):
            # Block bootstrap to preserve temporal autocorrelation
            block_size = max(4, self.lags)
            n_blocks = n // block_size
            indices = []
            starts = rng.integers(0, n - block_size, size=n_blocks)
            for s in starts:
                indices.extend(range(s, s + block_size))
            indices = indices[:n]
            sample = [prices[i] for i in indices]

            y = np.array(sample[self.lags:])
            X = np.column_stack([sample[i:len(sample)-self.lags+i] for i in range(self.lags)])
            X = np.hstack([np.ones((len(X), 1)), X])
            result = np.linalg.lstsq(X, y, rcond=None)
            coeffs = result[0]
            self._boot_intercepts.append(float(coeffs[0]))
            self._boot_coeffs.append(coeffs[1:])

    def predict(
        self,
        recent: list[float],
        horizon: int = 24,
        timestamps: list[datetime] | None = None,
    ) -> ForecastResult:
        """Predict with bootstrap confidence intervals."""
        assert self._boot_intercepts, "Must fit before predicting"

        all_preds = np.zeros((self.n_bootstrap, horizon))
        for b, (intercept, coeffs) in enumerate(zip(self._boot_intercepts, self._boot_coeffs)):
            window = list(recent[-self.lags:])
            for t in range(horizon):
                val = intercept + float(np.dot(coeffs, window[-self.lags:]))
                val = max(0.0, val)
                all_preds[b, t] = val
                window.append(val)

        mean = np.mean(all_preds, axis=0)
        p10 = np.percentile(all_preds, 10, axis=0)
        p90 = np.percentile(all_preds, 90, axis=0)

        if timestamps is None:
            now = datetime.now(timezone.utc)
            timestamps = [now + timedelta(hours=i + 1) for i in range(horizon)]

        return ForecastResult(
            timestamps=timestamps,
            mean=mean.tolist(),
            p10=np.maximum(0, p10).tolist(),
            p90=p90.tolist(),
            model=f"Bootstrap-AR-{self.n_bootstrap}",
        )
