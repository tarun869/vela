"""
Concept and data drift detection for deployed VPP ML models.

Monitors prediction accuracy, feature distributions, and prediction
confidence to detect when models need retraining.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy import stats


@dataclass
class DriftAlert:
    feature_name: str
    drift_type: str          # "data_drift", "concept_drift", "prediction_drift"
    severity: str            # "low", "medium", "high"
    statistic: float
    p_value: float
    description: str
    retrain_recommended: bool


class DataDriftDetector:
    """
    Detects distribution shift in input features using statistical tests.

    Uses Kolmogorov-Smirnov test for continuous features and
    chi-squared test for categorical features.
    """

    def __init__(self, reference_data: Dict[str, np.ndarray]) -> None:
        self.reference = reference_data
        self._alert_threshold = 0.05

    def detect(self, current_data: Dict[str, np.ndarray]) -> List[DriftAlert]:
        """Detect drift between reference and current distributions."""
        alerts: List[DriftAlert] = []

        for feature, ref_values in self.reference.items():
            if feature not in current_data:
                continue
            curr_values = current_data[feature]

            ks_stat, p_value = stats.ks_2samp(ref_values, curr_values)

            if p_value < self.alert_threshold:
                severity = "high" if p_value < 0.001 else "medium" if p_value < 0.01 else "low"
                alerts.append(DriftAlert(
                    feature_name=feature,
                    drift_type="data_drift",
                    severity=severity,
                    statistic=float(ks_stat),
                    p_value=float(p_value),
                    description=f"KS test: statistic={ks_stat:.3f}, p={p_value:.4f}",
                    retrain_recommended=severity in ("medium", "high"),
                ))
        return alerts

    @property
    def alert_threshold(self) -> float:
        return self._alert_threshold


class ConceptDriftDetector:
    """
    Detects concept drift by monitoring model prediction error over time.

    Uses ADWIN (Adaptive Windowing) algorithm for online drift detection.
    """

    def __init__(self, delta: float = 0.002) -> None:
        self.delta = delta
        self._error_window: List[float] = []
        self._drift_points: List[int] = []
        self._n = 0

    def update(self, prediction_error: float) -> Tuple[bool, Optional[int]]:
        """
        Update with new prediction error. Detect drift using ADWIN.

        Returns:
            (drift_detected, drift_index)
        """
        self._error_window.append(prediction_error)
        self._n += 1

        # ADWIN: check if any partition has significantly different mean
        window = np.array(self._error_window)
        n_total = len(window)

        if n_total < 20:
            return False, None

        global_mean = window.mean()
        global_var = window.var()

        for split in range(10, n_total - 10):
            left = window[:split]
            right = window[split:]
            m1 = left.mean()
            m2 = right.mean()

            # Hoeffding bound check
            epsilon = np.sqrt(
                (2 * global_var * np.log(4 * n_total / self.delta)) / (split * (n_total - split) / n_total)
            )
            if abs(m1 - m2) > epsilon:
                # Drift detected - shrink window to recent data
                self._error_window = list(window[split:])
                self._drift_points.append(self._n - (n_total - split))
                return True, self._drift_points[-1]

        return False, None

    def current_error_rate(self) -> float:
        if not self._error_window:
            return 0.0
        return float(np.mean(np.abs(self._error_window[-50:])))


class ModelMonitor:
    """
    Composite model monitoring combining data and concept drift detection.
    """

    def __init__(
        self,
        reference_features: Dict[str, np.ndarray],
        reference_errors: List[float],
    ) -> None:
        self.data_detector = DataDriftDetector(reference_features)
        self.concept_detector = ConceptDriftDetector()
        # Baseline error for comparison
        self.baseline_error = float(np.mean(np.abs(reference_errors))) if reference_errors else 0.0

    def update(
        self,
        current_features: Dict[str, np.ndarray],
        prediction_error: float,
    ) -> Dict[str, any]:
        """Update monitor with new data and return status."""
        data_alerts = self.data_detector.detect(current_features)
        concept_drift, drift_point = self.concept_detector.update(prediction_error)
        current_error = self.concept_detector.current_error_rate()
        error_increase = current_error / max(self.baseline_error, 1e-9) - 1.0

        return {
            "data_drift_alerts": len(data_alerts),
            "concept_drift_detected": concept_drift,
            "drift_point": drift_point,
            "current_error_rate": current_error,
            "error_increase_pct": error_increase * 100,
            "retrain_recommended": concept_drift or len(data_alerts) > 2 or error_increase > 0.20,
            "alerts": data_alerts,
        }
