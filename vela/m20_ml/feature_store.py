"""
Feature engineering and storage for VPP machine learning models.

Manages feature computation, versioning, and retrieval for
price forecasting, load forecasting, and dispatch optimization models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np


@dataclass
class Feature:
    name: str
    version: int
    dtype: str          # "float", "int", "bool", "categorical"
    description: str
    source: str         # "telemetry", "market", "weather", "derived"
    compute_fn: Optional[Callable] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class FeatureVector:
    feature_names: List[str]
    values: np.ndarray   # Shape (n_samples, n_features)
    timestamps: List[str]
    version_hash: str


class FeatureStore:
    """
    Centralized feature store for ML model inputs.

    Supports:
      - Feature registration and versioning
      - On-the-fly feature computation from raw data
      - Feature retrieval with point-in-time correctness
      - Feature statistics and monitoring
    """

    def __init__(self) -> None:
        self._features: Dict[str, Feature] = {}
        self._feature_data: Dict[str, Dict[str, Any]] = {}  # name -> {timestamp -> value}
        self._stats: Dict[str, Dict[str, float]] = {}

    def register_feature(self, feature: Feature) -> None:
        self._features[feature.name] = feature

    def write_feature_values(
        self,
        feature_name: str,
        timestamps: List[str],
        values: List[float],
    ) -> None:
        """Store feature values indexed by timestamp."""
        if feature_name not in self._feature_data:
            self._feature_data[feature_name] = {}
        for ts, val in zip(timestamps, values):
            self._feature_data[feature_name][ts] = val
        self._update_stats(feature_name, values)

    def _update_stats(self, feature_name: str, values: List[float]) -> None:
        arr = np.array(values)
        self._stats[feature_name] = {
            "mean": float(arr.mean()),
            "std": float(arr.std()),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "count": len(arr),
        }

    def get_feature_vector(
        self,
        feature_names: List[str],
        timestamps: List[str],
    ) -> FeatureVector:
        """
        Retrieve a feature matrix for given features and timestamps.

        Returns:
            FeatureVector with (n_timestamps, n_features) array.
        """
        n_ts = len(timestamps)
        n_feat = len(feature_names)
        matrix = np.zeros((n_ts, n_feat))

        for j, fname in enumerate(feature_names):
            data = self._feature_data.get(fname, {})
            for i, ts in enumerate(timestamps):
                matrix[i, j] = data.get(ts, float("nan"))

        version_hash = hex(hash(tuple(feature_names)))[:10]
        return FeatureVector(
            feature_names=feature_names,
            values=matrix,
            timestamps=timestamps,
            version_hash=version_hash,
        )

    def compute_lag_features(
        self,
        base_feature: str,
        lags: List[int],
        timestamps: List[str],
    ) -> Dict[str, List[float]]:
        """
        Compute lag features from a base feature.

        Returns:
            Dict of "feature_lag_N" -> values.
        """
        data = self._feature_data.get(base_feature, {})
        base_values = [data.get(ts, float("nan")) for ts in timestamps]
        result: Dict[str, List[float]] = {}

        for lag in lags:
            lag_values = [float("nan")] * lag + base_values[:-lag] if lag > 0 else base_values
            result[f"{base_feature}_lag_{lag}"] = lag_values[:len(timestamps)]

        return result

    def compute_rolling_features(
        self,
        base_feature: str,
        windows: List[int],
        timestamps: List[str],
        aggregations: List[str] = None,
    ) -> Dict[str, List[float]]:
        """
        Compute rolling window statistical features.

        Aggregations: "mean", "std", "min", "max".
        """
        aggregations = aggregations or ["mean", "std"]
        data = self._feature_data.get(base_feature, {})
        base_values = np.array([data.get(ts, float("nan")) for ts in timestamps])
        result: Dict[str, List[float]] = {}

        for window in windows:
            for agg in aggregations:
                key = f"{base_feature}_rolling_{window}_{agg}"
                agg_values = []
                for i in range(len(base_values)):
                    w_data = base_values[max(0, i - window + 1):i + 1]
                    valid = w_data[~np.isnan(w_data)]
                    if len(valid) == 0:
                        agg_values.append(float("nan"))
                    elif agg == "mean":
                        agg_values.append(float(valid.mean()))
                    elif agg == "std":
                        agg_values.append(float(valid.std()) if len(valid) > 1 else 0.0)
                    elif agg == "min":
                        agg_values.append(float(valid.min()))
                    elif agg == "max":
                        agg_values.append(float(valid.max()))
                result[key] = agg_values

        return result

    def feature_statistics(self) -> Dict[str, Dict[str, float]]:
        return dict(self._stats)

    def list_features(self) -> List[str]:
        return list(self._features.keys())
