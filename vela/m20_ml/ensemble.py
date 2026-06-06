"""
Ensemble methods for VPP price and load forecasting.

Implements stacking, bagging, and boosting ensembles
to improve forecast accuracy and robustness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
from numpy.random import default_rng


@dataclass
class EnsemblePrediction:
    mean: np.ndarray
    std: np.ndarray
    lower_80: np.ndarray
    upper_80: np.ndarray
    model_predictions: Dict[str, np.ndarray]
    weights: Dict[str, float]


class WeightedAverageEnsemble:
    """
    Weighted average ensemble of forecasting models.

    Weights can be fixed or optimized on a validation set.
    """

    def __init__(self, model_names: List[str]) -> None:
        self.model_names = model_names
        self.weights: Dict[str, float] = {name: 1.0 / len(model_names) for name in model_names}
        self._models: Dict[str, Any] = {}

    def add_model(self, name: str, model: Any) -> None:
        self._models[name] = model

    def fit_weights(
        self,
        X_val: np.ndarray,
        y_val: np.ndarray,
        method: str = "ols",
    ) -> None:
        """
        Optimize ensemble weights on validation data.

        Methods:
          - "ols": Non-negative least squares
          - "equal": Equal weights
          - "inverse_rmse": Weights inversely proportional to RMSE
        """
        predictions = {}
        for name, model in self._models.items():
            predictions[name] = model.predict(X_val)

        if method == "equal":
            n = len(self.model_names)
            self.weights = {name: 1.0 / n for name in self.model_names}

        elif method == "inverse_rmse":
            rmse_scores = {}
            for name, preds in predictions.items():
                residuals = y_val - preds
                rmse_scores[name] = float(np.sqrt((residuals ** 2).mean()))

            inv_rmse = {name: 1.0 / max(rmse, 1e-9) for name, rmse in rmse_scores.items()}
            total = sum(inv_rmse.values())
            self.weights = {name: v / total for name, v in inv_rmse.items()}

        elif method == "ols":
            # Stack predictions and solve non-negative least squares
            pred_matrix = np.column_stack([predictions[name] for name in self.model_names])
            # Ridge regression for weights
            A = pred_matrix.T @ pred_matrix + 1e-6 * np.eye(len(self.model_names))
            b = pred_matrix.T @ y_val
            raw_weights = np.linalg.solve(A, b)
            raw_weights = np.maximum(raw_weights, 0.0)
            total = raw_weights.sum()
            weights_arr = raw_weights / max(total, 1e-9)
            self.weights = {name: float(weights_arr[i]) for i, name in enumerate(self.model_names)}

    def predict(self, X: np.ndarray) -> EnsemblePrediction:
        """Generate ensemble prediction with uncertainty."""
        model_preds: Dict[str, np.ndarray] = {}
        for name, model in self._models.items():
            model_preds[name] = model.predict(X)

        weighted = sum(
            self.weights.get(name, 0.0) * preds
            for name, preds in model_preds.items()
        )

        # Uncertainty from disagreement between models
        pred_stack = np.column_stack(list(model_preds.values())) if model_preds else np.zeros((len(X), 1))
        std_pred = pred_stack.std(axis=1)

        z_80 = 1.282
        return EnsemblePrediction(
            mean=weighted,
            std=std_pred,
            lower_80=weighted - z_80 * std_pred,
            upper_80=weighted + z_80 * std_pred,
            model_predictions=model_preds,
            weights=dict(self.weights),
        )


class BaggingEnsemble:
    """
    Bootstrap aggregating ensemble with out-of-bag error estimation.
    """

    def __init__(
        self,
        base_model_fn: Callable,
        n_estimators: int = 10,
        subsample_fraction: float = 0.8,
        seed: int = 42,
    ) -> None:
        self.base_model_fn = base_model_fn
        self.n_estimators = n_estimators
        self.subsample_fraction = subsample_fraction
        self.rng = default_rng(seed)
        self._estimators: List[Any] = []
        self._oob_predictions: Optional[np.ndarray] = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> float:
        """
        Fit bagging ensemble and return OOB score.

        Returns:
            OOB RMSE score.
        """
        n = len(y)
        oob_preds = np.zeros(n)
        oob_counts = np.zeros(n)
        self._estimators = []

        for _ in range(self.n_estimators):
            bootstrap_idx = self.rng.choice(n, int(n * self.subsample_fraction), replace=True)
            oob_idx = np.setdiff1d(np.arange(n), bootstrap_idx)

            model = self.base_model_fn()
            model.fit(X[bootstrap_idx], y[bootstrap_idx])
            self._estimators.append(model)

            if len(oob_idx) > 0:
                oob_preds[oob_idx] += model.predict(X[oob_idx])
                oob_counts[oob_idx] += 1

        # OOB predictions
        valid = oob_counts > 0
        self._oob_predictions = np.where(valid, oob_preds / np.where(oob_counts > 0, oob_counts, 1), np.nan)
        oob_valid = y[valid] - self._oob_predictions[valid]
        oob_rmse = float(np.sqrt((oob_valid ** 2).mean())) if valid.any() else 0.0
        return oob_rmse

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Average predictions from all estimators."""
        if not self._estimators:
            raise RuntimeError("Ensemble not fitted")
        preds = np.column_stack([m.predict(X) for m in self._estimators])
        return preds.mean(axis=1)
