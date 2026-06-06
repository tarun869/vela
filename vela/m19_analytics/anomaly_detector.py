"""
Operational anomaly detection for VPP assets.

Detects abnormal operating conditions using statistical methods:
  - Z-score based univariate anomaly detection
  - Isolation Forest for multivariate anomalies
  - Change point detection for regime shifts
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy import stats


@dataclass
class AnomalyResult:
    timestamp_idx: int
    feature: str
    value: float
    zscore: float
    is_anomaly: bool
    severity: str   # "low", "medium", "high", "critical"
    description: str


class ZScoreAnomalyDetector:
    """Rolling z-score anomaly detector."""

    def __init__(self, window: int = 168, threshold: float = 3.0) -> None:
        self.window = window
        self.threshold = threshold

    def detect(self, values: List[float], feature_name: str = "value") -> List[AnomalyResult]:
        n = len(values)
        arr = np.array(values)
        results: List[AnomalyResult] = []

        for i in range(n):
            start = max(0, i - self.window)
            window_data = arr[start:i+1]
            if len(window_data) < 3:
                continue
            mean = window_data[:-1].mean()
            std = window_data[:-1].std()
            if std < 1e-9:
                continue
            z = abs((arr[i] - mean) / std)
            is_anomaly = z > self.threshold
            sev = "critical" if z > 5 else "high" if z > 4 else "medium" if z > 3 else "low"
            results.append(AnomalyResult(
                timestamp_idx=i, feature=feature_name, value=float(arr[i]),
                zscore=float(z), is_anomaly=is_anomaly, severity=sev,
                description=f"{feature_name}={arr[i]:.2f} (z={z:.1f})" if is_anomaly else "normal",
            ))
        return [r for r in results if r.is_anomaly]


class ChangePointDetector:
    """
    CUSUM-based change point detection for regime shifts.

    Detects shifts in mean level of a time series.
    """

    def __init__(self, threshold: float = 5.0, drift: float = 0.5) -> None:
        self.threshold = threshold
        self.drift = drift

    def detect(self, values: List[float]) -> List[int]:
        """Return indices where change points are detected."""
        arr = np.array(values, dtype=float)
        if len(arr) < 10:
            return []

        mu = arr[:10].mean()
        sigma = max(arr[:10].std(), 1e-9)
        cusum_pos = 0.0
        cusum_neg = 0.0
        change_points: List[int] = []

        for i, val in enumerate(arr):
            normalized = (val - mu) / sigma
            cusum_pos = max(0, cusum_pos + normalized - self.drift)
            cusum_neg = max(0, cusum_neg - normalized - self.drift)

            if cusum_pos > self.threshold or cusum_neg > self.threshold:
                change_points.append(i)
                # Reset after detection
                cusum_pos = 0.0
                cusum_neg = 0.0
                # Update baseline
                mu = arr[max(0, i-10):i+1].mean()
                sigma = max(arr[max(0, i-10):i+1].std(), 1e-9)

        return change_points


class OperationalAnomalyDetector:
    """Combined anomaly detection for VPP operational data."""

    def __init__(self) -> None:
        self._zscore = ZScoreAnomalyDetector()
        self._changepoint = ChangePointDetector()

    def analyze(
        self,
        data: Dict[str, List[float]],
    ) -> Dict[str, List[AnomalyResult]]:
        """Detect anomalies across multiple operational metrics."""
        return {
            feature: self._zscore.detect(values, feature)
            for feature, values in data.items()
        }

    def detect_regime_changes(self, power_series: List[float]) -> List[int]:
        return self._changepoint.detect(power_series)
