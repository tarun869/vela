"""
Hyperparameter tuning for VPP ML models.

Implements random search, Bayesian optimization (TPE-inspired),
and grid search with cross-validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
from numpy.random import default_rng


@dataclass
class SearchSpace:
    name: str
    low: float
    high: float
    log_scale: bool = False
    integer: bool = False


@dataclass
class HyperparameterResult:
    params: Dict[str, Any]
    cv_score: float
    train_score: float
    trial_id: int
    training_time_s: float


class RandomSearchTuner:
    """
    Random hyperparameter search with cross-validation.
    """

    def __init__(
        self,
        param_space: List[SearchSpace],
        n_trials: int = 50,
        seed: int = 42,
    ) -> None:
        self.param_space = param_space
        self.n_trials = n_trials
        self.rng = default_rng(seed)
        self._results: List[HyperparameterResult] = []

    def _sample_params(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for sp in self.param_space:
            if sp.log_scale:
                val = float(np.exp(self.rng.uniform(np.log(sp.low), np.log(sp.high))))
            else:
                val = float(self.rng.uniform(sp.low, sp.high))
            if sp.integer:
                val = int(round(val))
            params[sp.name] = val
        return params

    def search(
        self,
        objective_fn: Callable[[Dict[str, Any]], Tuple[float, float]],
    ) -> HyperparameterResult:
        """
        Run random search.

        Args:
            objective_fn: Function that takes params dict and returns (cv_score, train_score).

        Returns:
            Best HyperparameterResult.
        """
        import time
        for trial_id in range(self.n_trials):
            params = self._sample_params()
            t0 = time.time()
            cv_score, train_score = objective_fn(params)
            elapsed = time.time() - t0
            self._results.append(HyperparameterResult(
                params=params, cv_score=cv_score, train_score=train_score,
                trial_id=trial_id, training_time_s=elapsed,
            ))

        return min(self._results, key=lambda r: r.cv_score)

    def best_params(self) -> Dict[str, Any]:
        if not self._results:
            return {}
        best = min(self._results, key=lambda r: r.cv_score)
        return best.params

    def results_dataframe(self) -> List[Dict]:
        return [
            {"trial": r.trial_id, "cv_score": r.cv_score, **r.params}
            for r in self._results
        ]


class BayesianTuner:
    """
    Simple Gaussian Process-based Bayesian hyperparameter optimization.

    Uses surrogate model (GP) to guide search toward promising regions.
    """

    def __init__(
        self,
        param_space: List[SearchSpace],
        n_initial: int = 5,
        n_trials: int = 30,
        seed: int = 42,
    ) -> None:
        self.param_space = param_space
        self.n_initial = n_initial
        self.n_trials = n_trials
        self.rng = default_rng(seed)
        self._X: List[np.ndarray] = []
        self._y: List[float] = []

    def _to_array(self, params: Dict[str, Any]) -> np.ndarray:
        return np.array([params[sp.name] for sp in self.param_space], dtype=float)

    def _sample_random(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for sp in self.param_space:
            val = float(self.rng.uniform(sp.low, sp.high))
            if sp.integer:
                val = int(round(val))
            params[sp.name] = val
        return params

    def _gp_predict(self, x_new: np.ndarray) -> Tuple[float, float]:
        """Simplified GP prediction using RBF kernel."""
        if len(self._X) < 2:
            return 0.0, 1.0
        X = np.array(self._X)
        y = np.array(self._y)

        # RBF kernel
        length_scale = 1.0
        def rbf(a, b):
            return float(np.exp(-np.sum((a - b)**2) / (2 * length_scale**2)))

        K = np.array([[rbf(X[i], X[j]) for j in range(len(X))] for i in range(len(X))])
        K += 1e-6 * np.eye(len(X))
        k_star = np.array([rbf(x_new, X[i]) for i in range(len(X))])

        try:
            K_inv = np.linalg.inv(K)
            mu = float(k_star @ K_inv @ y)
            sigma = float(max(0.0, 1.0 - k_star @ K_inv @ k_star))
        except np.linalg.LinAlgError:
            mu, sigma = float(y.mean()), 1.0

        return mu, sigma

    def _acquisition_ei(self, x_new: np.ndarray, best_y: float) -> float:
        """Expected Improvement acquisition function."""
        mu, sigma = self._gp_predict(x_new)
        if sigma < 1e-9:
            return 0.0
        from scipy.stats import norm
        improvement = best_y - mu   # For minimization
        z = improvement / sigma
        return float(improvement * norm.cdf(z) + sigma * norm.pdf(z))

    def search(self, objective_fn: Callable) -> HyperparameterResult:
        """Run Bayesian optimization."""
        results: List[HyperparameterResult] = []
        import time

        # Initial random exploration
        for trial_id in range(self.n_initial):
            params = self._sample_random()
            t0 = time.time()
            cv_score, train_score = objective_fn(params)
            self._X.append(self._to_array(params))
            self._y.append(cv_score)
            results.append(HyperparameterResult(
                params=params, cv_score=cv_score, train_score=train_score,
                trial_id=trial_id, training_time_s=time.time() - t0,
            ))

        # Bayesian optimization
        for trial_id in range(self.n_initial, self.n_trials):
            best_y = min(self._y)
            # Sample candidates and pick highest EI
            n_candidates = 100
            candidates = [self._sample_random() for _ in range(n_candidates)]
            ei_scores = [
                self._acquisition_ei(self._to_array(c), best_y)
                for c in candidates
            ]
            best_candidate = candidates[np.argmax(ei_scores)]

            t0 = time.time()
            cv_score, train_score = objective_fn(best_candidate)
            self._X.append(self._to_array(best_candidate))
            self._y.append(cv_score)
            results.append(HyperparameterResult(
                params=best_candidate, cv_score=cv_score, train_score=train_score,
                trial_id=trial_id, training_time_s=time.time() - t0,
            ))

        return min(results, key=lambda r: r.cv_score)
