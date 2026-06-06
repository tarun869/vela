"""
Model training pipeline for VPP ML models.

Orchestrates data preparation, feature engineering, model training,
cross-validation, and evaluation for forecasting models.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
from numpy.random import default_rng


@dataclass
class TrainingConfig:
    model_name: str
    algorithm: str
    target: str
    features: List[str]
    hyperparameters: Dict[str, Any]
    n_splits: int = 5           # Time series cross-validation folds
    test_size_fraction: float = 0.2
    random_seed: int = 42


@dataclass
class TrainingResult:
    config: TrainingConfig
    train_metrics: Dict[str, float]
    val_metrics: Dict[str, float]
    test_metrics: Dict[str, float]
    feature_importance: Dict[str, float]
    cv_scores: List[float]
    training_time_s: float
    n_train_samples: int
    n_test_samples: int


class TimeSeriesCrossValidator:
    """
    Expanding-window cross-validation for time series data.
    """

    def __init__(self, n_splits: int = 5, min_train_size_fraction: float = 0.5) -> None:
        self.n_splits = n_splits
        self.min_train_size_fraction = min_train_size_fraction

    def split(self, n: int) -> List[Tuple[np.ndarray, np.ndarray]]:
        """Generate train/test index splits for time series CV."""
        min_train = int(n * self.min_train_size_fraction)
        splits: List[Tuple[np.ndarray, np.ndarray]] = []

        fold_size = (n - min_train) // self.n_splits
        for k in range(self.n_splits):
            train_end = min_train + k * fold_size
            test_start = train_end
            test_end = min(train_end + fold_size, n)
            if test_start >= n:
                break
            train_idx = np.arange(train_end)
            test_idx = np.arange(test_start, test_end)
            splits.append((train_idx, test_idx))

        return splits


def compute_regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Compute standard regression metrics."""
    residuals = y_true - y_pred
    mae = float(np.abs(residuals).mean())
    rmse = float(np.sqrt((residuals ** 2).mean()))
    mape = float(np.abs(residuals / np.where(np.abs(y_true) > 1e-9, y_true, 1e-9)).mean() * 100)
    ss_res = float((residuals ** 2).sum())
    ss_tot = float(((y_true - y_true.mean()) ** 2).sum())
    r2 = 1 - ss_res / max(ss_tot, 1e-9)
    return {"mae": mae, "rmse": rmse, "mape": mape, "r2": r2}


class SimpleLinearModel:
    """
    Lightweight linear regression model for price/load forecasting.
    Implements OLS with ridge regularization.
    """

    def __init__(self, alpha: float = 0.01) -> None:
        self.alpha = alpha
        self.weights: Optional[np.ndarray] = None
        self.bias: float = 0.0
        self.feature_names: List[str] = []

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Fit ridge regression: w = (X'X + alpha*I)^-1 X'y."""
        n, p = X.shape
        X_bias = np.column_stack([np.ones(n), X])
        A = X_bias.T @ X_bias + self.alpha * np.eye(p + 1)
        b = X_bias.T @ y
        w = np.linalg.solve(A, b)
        self.bias = float(w[0])
        self.weights = w[1:]

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.weights is None:
            raise RuntimeError("Model not fitted")
        return X @ self.weights + self.bias

    def feature_importance(self) -> np.ndarray:
        if self.weights is None:
            return np.array([])
        return np.abs(self.weights) / (np.abs(self.weights).sum() + 1e-9)


class TrainingPipeline:
    """
    End-to-end training pipeline for VPP ML models.
    """

    def __init__(self, config: TrainingConfig) -> None:
        self.config = config
        self._cv = TimeSeriesCrossValidator(config.n_splits)

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        model_fn: Optional[Callable] = None,
    ) -> Tuple[Any, TrainingResult]:
        """
        Train model with cross-validation and return results.

        Args:
            X: Feature matrix (n_samples, n_features).
            y: Target array (n_samples,).
            model_fn: Factory function returning a model with fit/predict.

        Returns:
            (fitted_model, TrainingResult)
        """
        import time
        t0 = time.time()
        n = len(y)
        test_n = int(n * self.config.test_size_fraction)
        train_n = n - test_n

        X_train, X_test = X[:train_n], X[train_n:]
        y_train, y_test = y[:train_n], y[train_n:]

        # Cross-validation
        cv_splits = self._cv.split(train_n)
        cv_scores: List[float] = []
        for tr_idx, val_idx in cv_splits:
            model = SimpleLinearModel(self.config.hyperparameters.get("alpha", 0.01))
            model.fit(X_train[tr_idx], y_train[tr_idx])
            y_val_pred = model.predict(X_train[val_idx])
            metrics = compute_regression_metrics(y_train[val_idx], y_val_pred)
            cv_scores.append(metrics["rmse"])

        # Final model on all training data
        final_model = SimpleLinearModel(self.config.hyperparameters.get("alpha", 0.01))
        final_model.fit(X_train, y_train)

        train_metrics = compute_regression_metrics(y_train, final_model.predict(X_train))
        test_metrics = compute_regression_metrics(y_test, final_model.predict(X_test))

        # Feature importance
        importance = final_model.feature_importance()
        feat_imp = {
            self.config.features[i]: float(importance[i])
            for i in range(min(len(self.config.features), len(importance)))
        }

        result = TrainingResult(
            config=self.config,
            train_metrics=train_metrics,
            val_metrics={"rmse": float(np.mean(cv_scores))},
            test_metrics=test_metrics,
            feature_importance=feat_imp,
            cv_scores=cv_scores,
            training_time_s=time.time() - t0,
            n_train_samples=train_n,
            n_test_samples=test_n,
        )
        return final_model, result
