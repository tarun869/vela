"""
ML model explanation for VPP forecasting and dispatch decisions.

Implements SHAP-inspired feature attribution and counterfactual
explanations for model predictions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from itertools import combinations


@dataclass
class FeatureContribution:
    feature_name: str
    value: float
    contribution: float   # SHAP value (marginal contribution to prediction)
    pct_contribution: float


@dataclass
class ExplanationResult:
    prediction: float
    base_value: float   # Expected prediction (mean of training set)
    contributions: List[FeatureContribution]
    top_positive: List[str]   # Top features pushing prediction up
    top_negative: List[str]   # Top features pushing prediction down
    explanation_text: str


class ShapExplainer:
    """
    Approximate SHAP (SHapley Additive exPlanations) using
    kernel SHAP sampling approach.
    """

    def __init__(
        self,
        model: Any,           # Any model with predict(X) method
        background_data: np.ndarray,  # Reference distribution (n_bg, n_features)
        feature_names: List[str],
    ) -> None:
        self.model = model
        self.background = background_data
        self.feature_names = feature_names
        self.n_features = len(feature_names)
        self.base_value = float(model.predict(background_data).mean())

    def explain_instance(
        self,
        instance: np.ndarray,   # Shape (n_features,)
        n_samples: int = 100,
    ) -> ExplanationResult:
        """
        Compute approximate SHAP values for a single prediction.

        Uses random feature coalitions to estimate Shapley values.
        """
        rng = np.random.default_rng(42)
        shapley_values = np.zeros(self.n_features)
        n_bg = len(self.background)

        # Sample background points
        bg_idx = rng.integers(0, n_bg, min(50, n_bg))
        bg_samples = self.background[bg_idx]

        for _ in range(n_samples):
            # Random permutation of features
            perm = rng.permutation(self.n_features)

            # For each feature, compute marginal contribution
            for k_pos, feat_idx in enumerate(perm):
                # Coalition with feature included
                subset_with = perm[:k_pos + 1]
                # Coalition without feature
                subset_without = perm[:k_pos]

                # Average prediction with feature over background
                X_with = bg_samples.copy()
                X_with[:, subset_with] = instance[subset_with]
                pred_with = self.model.predict(X_with).mean()

                if len(subset_without) > 0:
                    X_without = bg_samples.copy()
                    X_without[:, subset_without] = instance[subset_without]
                    pred_without = self.model.predict(X_without).mean()
                else:
                    pred_without = self.base_value

                shapley_values[feat_idx] += pred_with - pred_without

        shapley_values /= n_samples
        prediction = float(self.model.predict(instance.reshape(1, -1))[0])

        total_abs = np.abs(shapley_values).sum() + 1e-9
        contributions = [
            FeatureContribution(
                feature_name=self.feature_names[i],
                value=float(instance[i]),
                contribution=float(shapley_values[i]),
                pct_contribution=float(abs(shapley_values[i]) / total_abs * 100),
            )
            for i in range(self.n_features)
        ]
        contributions.sort(key=lambda c: abs(c.contribution), reverse=True)

        top_pos = [c.feature_name for c in contributions if c.contribution > 0][:3]
        top_neg = [c.feature_name for c in contributions if c.contribution < 0][:3]

        explanation_text = (
            f"Prediction: {prediction:.2f} (base: {self.base_value:.2f}). "
            f"Top drivers: {', '.join(top_pos[:2])}. "
            f"Downward factors: {', '.join(top_neg[:2])}."
        )

        return ExplanationResult(
            prediction=prediction,
            base_value=self.base_value,
            contributions=contributions,
            top_positive=top_pos,
            top_negative=top_neg,
            explanation_text=explanation_text,
        )

    def feature_importance_global(
        self, X: np.ndarray, n_samples: int = 50
    ) -> Dict[str, float]:
        """
        Compute global feature importance as mean |SHAP| across instances.
        """
        importance = np.zeros(self.n_features)
        sample_idx = np.random.choice(len(X), min(n_samples, len(X)), replace=False)
        for i in sample_idx:
            result = self.explain_instance(X[i], n_samples=20)
            for c in result.contributions:
                idx = self.feature_names.index(c.feature_name)
                importance[idx] += abs(c.contribution)
        importance /= len(sample_idx)
        return {self.feature_names[i]: float(importance[i]) for i in range(self.n_features)}
