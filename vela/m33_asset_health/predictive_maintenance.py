"""
Predictive maintenance modeling for VPP assets.

Uses time-to-failure distributions and survival analysis to predict
maintenance needs before they become operational failures.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy import stats


@dataclass
class FailureHistory:
    asset_id: str
    component: str
    failure_times_h: List[float]   # Hours of operation at each failure
    censored: bool = False          # True if still running (right-censored)


@dataclass
class WeibullFit:
    shape: float    # Beta parameter (>1 = wear-out, <1 = early failure)
    scale: float    # Eta parameter (characteristic life in hours)
    r_squared: float


@dataclass
class MaintenanceRecommendation:
    asset_id: str
    component: str
    hours_to_maintenance: float
    failure_probability_30d: float
    recommended_action: str
    estimated_cost_usd: float


class WeibullSurvivalModel:
    """
    Weibull survival analysis for VPP component reliability.

    Weibull distribution is the standard for mechanical and electrical
    component lifetime modeling.
    """

    def fit(self, failure_times: List[float]) -> WeibullFit:
        """
        Fit Weibull distribution to failure times using MLE.

        Uses log-linear regression on the Weibull cumulative distribution.
        """
        n = len(failure_times)
        if n < 2:
            return WeibullFit(shape=1.0, scale=float(failure_times[0]) if failure_times else 1000.0, r_squared=0.0)

        times = np.sort(np.array(failure_times, dtype=float))
        # Median rank (Benard's approximation)
        ranks = (np.arange(1, n + 1) - 0.3) / (n + 0.4)
        y = np.log(-np.log(1 - ranks + 1e-9))
        x = np.log(times + 1e-9)

        slope, intercept, r_value, _, _ = stats.linregress(x, y)
        shape = float(slope)
        scale = float(np.exp(-intercept / shape))

        return WeibullFit(shape=shape, scale=scale, r_squared=float(r_value ** 2))

    def failure_probability(
        self, fit: WeibullFit, current_hours: float, interval_hours: float
    ) -> float:
        """P(failure in next interval_hours | survived current_hours)."""
        t1 = current_hours
        t2 = current_hours + interval_hours
        # Conditional probability: F(t2) - F(t1) / R(t1)
        f1 = 1 - np.exp(-(t1 / fit.scale) ** fit.shape)
        f2 = 1 - np.exp(-(t2 / fit.scale) ** fit.shape)
        r1 = max(1 - f1, 1e-9)
        return float((f2 - f1) / r1)

    def remaining_useful_life(
        self, fit: WeibullFit, current_hours: float, target_reliability: float = 0.90
    ) -> float:
        """Hours until reliability falls below target_reliability."""
        # R(t) = exp(-(t/eta)^beta) -> solve for t at R = target
        t_target = fit.scale * (-np.log(target_reliability)) ** (1.0 / fit.shape)
        return max(0.0, t_target - current_hours)


class PredictiveMaintenanceEngine:
    """Builds and serves maintenance recommendations from Weibull models."""

    def __init__(self) -> None:
        self._models: Dict[str, WeibullFit] = {}
        self._model = WeibullSurvivalModel()

    def train(self, history: FailureHistory) -> WeibullFit:
        key = f"{history.asset_id}_{history.component}"
        fit = self._model.fit(history.failure_times_h)
        self._models[key] = fit
        return fit

    def recommend(
        self,
        asset_id: str,
        component: str,
        current_hours: float,
        maintenance_cost_usd: float,
    ) -> MaintenanceRecommendation:
        key = f"{asset_id}_{component}"
        fit = self._models.get(key, WeibullFit(shape=2.0, scale=8760.0, r_squared=0.0))
        p30d = self._model.failure_probability(fit, current_hours, 720.0)
        rul = self._model.remaining_useful_life(fit, current_hours)

        if p30d > 0.30:
            action = "immediate_maintenance"
        elif p30d > 0.10:
            action = "schedule_within_2_weeks"
        elif rul < 720:
            action = "schedule_within_month"
        else:
            action = "monitor"

        return MaintenanceRecommendation(
            asset_id=asset_id,
            component=component,
            hours_to_maintenance=rul,
            failure_probability_30d=p30d,
            recommended_action=action,
            estimated_cost_usd=maintenance_cost_usd,
        )
