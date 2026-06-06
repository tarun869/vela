"""Forecast calibration and post-processing using isotonic regression and reliability diagrams."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import NamedTuple


class CalibrationMetrics(NamedTuple):
    reliability_score: float    # Calibration error (lower is better)
    sharpness: float            # Average interval width (lower is sharper)
    coverage_p10_p90: float     # Fraction of actuals within 10-90 PI
    mae: float
    rmse: float
    skill_score: float          # vs. climatology baseline


@dataclass
class IsotonicCalibrator:
    """
    Post-processing calibrator using isotonic regression.

    Corrects systematic biases in probabilistic forecasts.
    Calibrates predicted quantiles to match empirical quantiles.
    """
    quantiles: list[float] = field(default_factory=lambda: [0.1, 0.25, 0.5, 0.75, 0.9])
    _iso_intercepts: dict[float, float] = field(default_factory=dict, init=False, repr=False)
    _iso_slopes: dict[float, float] = field(default_factory=dict, init=False, repr=False)
    _fitted: bool = field(default=False, init=False, repr=False)

    def fit(
        self,
        predicted_quantiles: dict[float, list[float]],
        actuals: list[float],
    ) -> None:
        """
        Fit calibration mapping from predicted to calibrated quantile values.

        Parameters
        ----------
        predicted_quantiles : dict
            Mapping of quantile -> list of predicted values
        actuals : list[float]
            Observed values
        """
        y = np.array(actuals)
        for q in self.quantiles:
            if q not in predicted_quantiles:
                continue
            yhat_q = np.array(predicted_quantiles[q])
            # Sort by predicted quantile values
            sort_idx = np.argsort(yhat_q)
            yhat_sorted = yhat_q[sort_idx]
            y_sorted = y[sort_idx]

            # Isotonic regression via PAVA (Pool Adjacent Violators)
            n = len(y_sorted)
            target_empirical = np.array([
                float(np.mean(y_sorted[:i+1] <= np.percentile(y_sorted, q * 100)))
                for i in range(n)
            ])
            # Linear fit for simplicity (in production: use sklearn.isotonic)
            if len(yhat_sorted) > 1:
                slope, intercept = np.polyfit(yhat_sorted, target_empirical, 1)
                self._iso_slopes[q] = float(slope)
                self._iso_intercepts[q] = float(intercept)
            else:
                self._iso_slopes[q] = 1.0
                self._iso_intercepts[q] = 0.0

        self._fitted = True

    def calibrate(self, raw_quantiles: dict[float, list[float]]) -> dict[float, list[float]]:
        """Apply learned calibration to raw forecast quantiles."""
        if not self._fitted:
            return raw_quantiles  # passthrough if not fitted

        calibrated = {}
        for q, values in raw_quantiles.items():
            if q in self._iso_slopes:
                slope = self._iso_slopes[q]
                intercept = self._iso_intercepts[q]
                arr = np.array(values)
                calibrated[q] = np.maximum(0, arr * slope + intercept * arr.mean()).tolist()
            else:
                calibrated[q] = values
        return calibrated


@dataclass
class ForecastEvaluator:
    """
    Evaluates probabilistic forecast quality.

    Implements standard metrics from energy forecasting literature:
    - CRPS (Continuous Ranked Probability Score)
    - Pinball loss
    - Coverage
    - Reliability
    - Skill score vs. persistence baseline
    """

    def evaluate(
        self,
        actuals: list[float],
        mean_forecast: list[float],
        p10: list[float],
        p90: list[float],
    ) -> CalibrationMetrics:
        """Compute calibration and accuracy metrics."""
        y = np.array(actuals)
        yhat = np.array(mean_forecast)
        lo = np.array(p10)
        hi = np.array(p90)

        mae = float(np.mean(np.abs(y - yhat)))
        rmse = float(np.sqrt(np.mean((y - yhat) ** 2)))

        # Coverage: fraction of actuals within [p10, p90]
        coverage = float(np.mean((y >= lo) & (y <= hi)))

        # Sharpness: average interval width
        sharpness = float(np.mean(hi - lo))

        # Reliability: calibration error (how far coverage is from 80%)
        reliability = float(abs(coverage - 0.80))

        # Skill score: RMSE relative to naive climatology (mean forecast)
        climatology_rmse = float(np.std(y))
        skill = 1.0 - rmse / (climatology_rmse + 1e-6)

        return CalibrationMetrics(
            reliability_score=reliability,
            sharpness=sharpness,
            coverage_p10_p90=coverage,
            mae=mae,
            rmse=rmse,
            skill_score=skill,
        )

    def pinball_loss(
        self,
        actuals: list[float],
        forecast_quantile: list[float],
        quantile: float,
    ) -> float:
        """
        Pinball (quantile) loss — proper scoring rule for quantile forecasts.

        Loss = q * max(y - yhat, 0) + (1-q) * max(yhat - y, 0)
        """
        y = np.array(actuals)
        yhat = np.array(forecast_quantile)
        diff = y - yhat
        loss = np.where(diff >= 0, quantile * diff, (quantile - 1) * diff)
        return float(np.mean(loss))

    def crps(
        self,
        actuals: list[float],
        ensemble_forecasts: np.ndarray,
    ) -> float:
        """
        Continuous Ranked Probability Score.

        Parameters
        ----------
        ensemble_forecasts : np.ndarray
            Shape (n_samples, n_scenarios) — ensemble members
        """
        y = np.array(actuals)
        n_scenarios = ensemble_forecasts.shape[1]
        # Energy score approximation of CRPS
        scores = []
        for i, yi in enumerate(y):
            members = ensemble_forecasts[i]
            # E[|X - y|] - 0.5 * E[|X - X'|]
            term1 = np.mean(np.abs(members - yi))
            # Pairwise differences
            term2 = 0.0
            for j in range(n_scenarios):
                for k in range(j + 1, n_scenarios):
                    term2 += abs(members[j] - members[k])
            term2 = term2 / (n_scenarios * (n_scenarios - 1) / 2 + 1e-8)
            scores.append(term1 - 0.5 * term2)
        return float(np.mean(scores))

    def reliability_diagram_data(
        self,
        actuals: list[float],
        quantile_forecasts: dict[float, list[float]],
        n_bins: int = 10,
    ) -> dict[float, tuple[list[float], list[float]]]:
        """
        Generate data for reliability (calibration) diagrams.

        Returns dict: quantile -> (predicted_frequencies, empirical_frequencies)
        """
        y = np.array(actuals)
        result = {}
        for q, forecasts in quantile_forecasts.items():
            yhat_q = np.array(forecasts)
            # Empirical coverage at this quantile
            empirical = float(np.mean(y <= yhat_q))
            result[q] = ([q], [empirical])
        return result
