"""Gaussian Process regression for LMP price uncertainty quantification."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, NamedTuple


class GPForecast(NamedTuple):
    timestamps: list[datetime]
    mean: list[float]
    variance: list[float]
    p10: list[float]
    p90: list[float]
    model: str


# ---------------------------------------------------------------------------
# Kernel functions
# ---------------------------------------------------------------------------

def rbf_kernel(x1: np.ndarray, x2: np.ndarray, length_scale: float, amplitude: float) -> np.ndarray:
    """Radial Basis Function (squared exponential) kernel."""
    diff = x1[:, None] - x2[None, :]  # shape (n, m)
    return amplitude ** 2 * np.exp(-0.5 * (diff / length_scale) ** 2)


def periodic_kernel(
    x1: np.ndarray,
    x2: np.ndarray,
    length_scale: float,
    period: float,
    amplitude: float,
) -> np.ndarray:
    """Periodic kernel — captures daily/weekly seasonality."""
    diff = np.abs(x1[:, None] - x2[None, :])
    return amplitude ** 2 * np.exp(-2 * np.sin(np.pi * diff / period) ** 2 / length_scale ** 2)


def matern52_kernel(x1: np.ndarray, x2: np.ndarray, length_scale: float, amplitude: float) -> np.ndarray:
    """Matern 5/2 kernel — more realistic roughness for energy prices."""
    diff = np.abs(x1[:, None] - x2[None, :])
    r = np.sqrt(5) * diff / length_scale
    return amplitude ** 2 * (1 + r + r ** 2 / 3) * np.exp(-r)


@dataclass
class GPPriceModel:
    """
    Gaussian Process regression for LMP price forecasting with uncertainty.

    Uses a composite kernel: RBF (trend) + Periodic (daily cycle) + noise.
    Inference is exact (Cholesky factorisation), O(n^3) in training points.
    For large datasets, use sparse GP approximations.
    """
    length_scale_rbf: float = 12.0    # hours — trend smoothness
    amplitude_rbf: float = 10.0       # $/MWh
    period_hours: float = 24.0        # diurnal period
    length_scale_per: float = 2.0     # periodic length scale
    amplitude_per: float = 8.0        # $/MWh
    noise_sigma: float = 2.0          # observation noise $/MWh
    _X_train: np.ndarray = field(default=None, init=False, repr=False)
    _y_train: np.ndarray = field(default=None, init=False, repr=False)
    _L: np.ndarray = field(default=None, init=False, repr=False)
    _alpha: np.ndarray = field(default=None, init=False, repr=False)
    _fitted: bool = field(default=False, init=False, repr=False)

    def _kernel(self, x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
        """Composite kernel = RBF + Periodic."""
        K = rbf_kernel(x1, x2, self.length_scale_rbf, self.amplitude_rbf)
        K += periodic_kernel(x1, x2, self.length_scale_per, self.period_hours, self.amplitude_per)
        return K

    def fit(self, hours: list[float], prices: list[float]) -> None:
        """
        Fit GP to observed data.

        Parameters
        ----------
        hours : list[float]
            Time in hours from some reference (e.g. 0, 1, 2, ..., N-1)
        prices : list[float]
            Observed LMP in $/MWh
        """
        X = np.array(hours, dtype=float)
        y = np.array(prices, dtype=float)
        self._X_train = X
        self._y_train = y

        K = self._kernel(X, X)
        K += (self.noise_sigma ** 2) * np.eye(len(X))

        # Cholesky for numerical stability
        K += 1e-8 * np.eye(len(X))  # jitter
        try:
            self._L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            # Fallback: add more jitter
            K += 1e-4 * np.eye(len(X))
            self._L = np.linalg.cholesky(K)

        self._alpha = np.linalg.solve(self._L.T, np.linalg.solve(self._L, y))
        self._fitted = True

    def predict(
        self,
        forecast_hours: list[float],
        timestamps: list[datetime] | None = None,
    ) -> GPForecast:
        """
        Predict mean and variance at new time points.

        Parameters
        ----------
        forecast_hours : list[float]
            Target time points in hours
        timestamps : list[datetime], optional
            Wall-clock timestamps for output labeling
        """
        assert self._fitted, "GP must be fitted before prediction"
        X_star = np.array(forecast_hours, dtype=float)

        K_star = self._kernel(X_star, self._X_train)
        K_ss = self._kernel(X_star, X_star)

        # Posterior mean
        mean = K_star @ self._alpha

        # Posterior variance
        v = np.linalg.solve(self._L, K_star.T)
        var = np.diag(K_ss) - np.sum(v ** 2, axis=0)
        var = np.maximum(var, 1e-8)  # numerical safety

        std = np.sqrt(var)
        mean_clipped = np.maximum(mean, 0.0)

        if timestamps is None:
            now = datetime.now(timezone.utc)
            timestamps = [now + timedelta(hours=int(h)) for h in forecast_hours]

        return GPForecast(
            timestamps=timestamps,
            mean=mean_clipped.tolist(),
            variance=var.tolist(),
            p10=[max(0, m - 1.28 * s) for m, s in zip(mean_clipped, std)],
            p90=[(m + 1.28 * s) for m, s in zip(mean_clipped, std)],
            model="GP-RBF+Periodic",
        )

    def log_marginal_likelihood(self) -> float:
        """Compute the log marginal likelihood for hyper-parameter selection."""
        assert self._fitted
        n = len(self._y_train)
        log_det = 2 * np.sum(np.log(np.diag(self._L)))
        lml = (
            -0.5 * float(self._y_train @ self._alpha)
            - 0.5 * log_det
            - 0.5 * n * np.log(2 * np.pi)
        )
        return lml

    def optimize_hyperparams(
        self,
        hours: list[float],
        prices: list[float],
        n_restarts: int = 5,
        rng_seed: int = 0,
    ) -> dict[str, float]:
        """
        Simple grid + random-restart optimization of length_scale_rbf and noise_sigma
        via log marginal likelihood.  Returns best hyperparams found.
        """
        rng = np.random.default_rng(rng_seed)
        best_lml = -np.inf
        best_params: dict[str, float] = {}

        for _ in range(n_restarts):
            ls = float(rng.uniform(4, 48))
            ns = float(rng.uniform(0.5, 10.0))
            self.length_scale_rbf = ls
            self.noise_sigma = ns
            try:
                self.fit(hours, prices)
                lml = self.log_marginal_likelihood()
                if lml > best_lml:
                    best_lml = lml
                    best_params = {"length_scale_rbf": ls, "noise_sigma": ns, "lml": lml}
            except Exception:
                pass

        # Apply best params and refit
        if best_params:
            self.length_scale_rbf = best_params["length_scale_rbf"]
            self.noise_sigma = best_params["noise_sigma"]
            self.fit(hours, prices)

        return best_params
