"""SHAP-based feature importance for forecast models."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import NamedTuple


class SHAPResult(NamedTuple):
    feature_names: list[str]
    shap_values: np.ndarray        # shape (n_samples, n_features)
    base_value: float
    mean_abs_shap: np.ndarray      # mean |shap| per feature
    top_features: list[str]        # sorted by importance


@dataclass
class KernelSHAPExplainer:
    """
    Kernel SHAP explainer for black-box forecast models.

    Implements a simplified version of kernel SHAP using weighted linear regression
    on coalitions of feature subsets.  This is model-agnostic and works with any
    Python callable.

    Reference: Lundberg & Lee (2017) — A Unified Approach to Interpreting Model Predictions
    """
    n_samples: int = 500
    seed: int = 42

    def explain(
        self,
        predict_fn,
        background_data: np.ndarray,
        instance: np.ndarray,
        feature_names: list[str] | None = None,
    ) -> SHAPResult:
        """
        Compute SHAP values for a single prediction instance.

        Parameters
        ----------
        predict_fn : callable
            Model prediction function f(X) -> np.ndarray
        background_data : np.ndarray
            Shape (n_background, n_features) — reference distribution
        instance : np.ndarray
            Shape (n_features,) — instance to explain
        feature_names : list[str], optional

        Returns
        -------
        SHAPResult
        """
        rng = np.random.default_rng(self.seed)
        n_features = instance.shape[0]
        if feature_names is None:
            feature_names = [f"feature_{i}" for i in range(n_features)]

        base_value = float(np.mean(predict_fn(background_data)))

        # Generate coalition samples (binary masks)
        n_coalitions = min(self.n_samples, 2 ** n_features)
        masks = rng.integers(0, 2, size=(n_coalitions, n_features)).astype(float)
        # Always include all-on and all-off
        masks[0] = np.zeros(n_features)
        masks[1] = np.ones(n_features)

        # Kernel SHAP weights: w(|z|) = (M-1) / (C(M, |z|) * |z| * (M - |z|))
        M = n_features
        weights = np.ones(n_coalitions)
        for idx, mask in enumerate(masks):
            z = int(mask.sum())
            if z == 0 or z == M:
                weights[idx] = 1e6  # Near-infinite weight for boundary cases
            else:
                import math
                comb = math.comb(M, z)
                weights[idx] = (M - 1) / (comb * z * (M - z) + 1e-10)

        # Evaluate model on masked inputs
        y_vals = np.zeros(n_coalitions)
        for idx, mask in enumerate(masks):
            # Masked input: use instance where mask=1, background mean where mask=0
            bg_mean = np.mean(background_data, axis=0)
            x_masked = np.where(mask, instance, bg_mean)
            y_vals[idx] = float(np.mean(predict_fn(x_masked.reshape(1, -1))))

        # Weighted least squares: phi = (Z^T W Z)^{-1} Z^T W y
        Z = np.hstack([np.ones((n_coalitions, 1)), masks])
        W = np.diag(weights)
        try:
            ZtWZ = Z.T @ W @ Z
            ZtWy = Z.T @ W @ y_vals
            coeffs = np.linalg.solve(ZtWZ + 1e-6 * np.eye(M + 1), ZtWy)
        except np.linalg.LinAlgError:
            coeffs = np.zeros(M + 1)

        shap_vals = coeffs[1:]  # phi_1, ..., phi_M
        mean_abs = np.abs(shap_vals)

        sorted_idx = np.argsort(-mean_abs)
        top_features = [feature_names[i] for i in sorted_idx[:10]]

        return SHAPResult(
            feature_names=feature_names,
            shap_values=shap_vals.reshape(1, -1),
            base_value=base_value,
            mean_abs_shap=mean_abs,
            top_features=top_features,
        )

    def batch_explain(
        self,
        predict_fn,
        background_data: np.ndarray,
        instances: np.ndarray,
        feature_names: list[str] | None = None,
    ) -> SHAPResult:
        """
        Compute SHAP values for multiple instances.

        Returns aggregated SHAP values across all instances.
        """
        n_features = instances.shape[1]
        all_shap = np.zeros((len(instances), n_features))
        base_values = []

        for i, inst in enumerate(instances):
            result = self.explain(predict_fn, background_data, inst, feature_names)
            all_shap[i] = result.shap_values[0]
            base_values.append(result.base_value)

        mean_abs = np.mean(np.abs(all_shap), axis=0)
        if feature_names is None:
            feature_names = [f"feature_{j}" for j in range(n_features)]
        sorted_idx = np.argsort(-mean_abs)
        top_features = [feature_names[j] for j in sorted_idx[:10]]

        return SHAPResult(
            feature_names=feature_names,
            shap_values=all_shap,
            base_value=float(np.mean(base_values)),
            mean_abs_shap=mean_abs,
            top_features=top_features,
        )

    def waterfall_data(
        self,
        result: SHAPResult,
        instance_idx: int = 0,
    ) -> list[dict]:
        """
        Prepare data for a waterfall plot.

        Returns list of dicts with feature, value, contribution, running_total.
        """
        shap_vals = result.shap_values[instance_idx]
        sorted_idx = np.argsort(-np.abs(shap_vals))
        running = result.base_value
        bars = []
        for idx in sorted_idx:
            contribution = float(shap_vals[idx])
            bars.append({
                "feature": result.feature_names[idx],
                "shap_value": contribution,
                "running_total": running + contribution,
                "base": running,
            })
            running += contribution
        return bars
