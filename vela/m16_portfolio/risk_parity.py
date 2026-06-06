"""
Risk parity (equal risk contribution) portfolio allocation for VPP assets.

Each asset contributes equally to portfolio risk (CVaR or variance).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
from scipy.optimize import minimize


@dataclass
class RiskParityResult:
    weights: Dict[str, float]
    risk_contributions: Dict[str, float]    # Each asset's risk contribution
    portfolio_volatility: float
    max_risk_contribution: float
    min_risk_contribution: float
    gini_coefficient: float   # 0 = perfect parity, 1 = all risk in one asset


class RiskParityOptimizer:
    """
    Risk parity portfolio optimizer.

    Objective: minimize sum of squared differences in risk contributions.

    Risk contribution of asset i:
        RC_i = w_i * (Sigma @ w)_i / sqrt(w^T Sigma w)
    """

    def __init__(self, asset_ids: List[str], cov_matrix: np.ndarray) -> None:
        self.asset_ids = asset_ids
        self.n = len(asset_ids)
        self.cov = cov_matrix
        assert cov_matrix.shape == (self.n, self.n)

    def _risk_contributions(self, weights: np.ndarray) -> np.ndarray:
        """Compute marginal risk contributions for each asset."""
        port_var = float(weights @ self.cov @ weights)
        port_std = float(np.sqrt(max(port_var, 1e-12)))
        mrc = self.cov @ weights / port_std   # Marginal risk contributions
        rc = weights * mrc                     # Risk contributions
        return rc

    def _objective(self, weights: np.ndarray) -> float:
        """Minimize squared difference from equal risk contribution."""
        rc = self._risk_contributions(weights)
        target_rc = rc.sum() / self.n
        return float(np.sum((rc - target_rc) ** 2))

    def _objective_grad(self, weights: np.ndarray) -> np.ndarray:
        """Analytical gradient via finite differences."""
        eps = 1e-6
        grad = np.zeros(self.n)
        f0 = self._objective(weights)
        for i in range(self.n):
            w_plus = weights.copy()
            w_plus[i] += eps
            grad[i] = (self._objective(w_plus) - f0) / eps
        return grad

    def optimize(
        self,
        lb: Optional[float] = 0.01,
        ub: Optional[float] = 1.0,
    ) -> RiskParityResult:
        """
        Find risk parity weights.

        Args:
            lb: Lower bound per asset weight.
            ub: Upper bound per asset weight.

        Returns:
            RiskParityResult.
        """
        w0 = np.ones(self.n) / self.n
        constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        bounds = [(lb or 0.0, ub or 1.0)] * self.n

        result = minimize(
            self._objective,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-10, "maxiter": 2000},
        )

        weights = result.x if result.success else w0
        weights = np.maximum(weights, 0.0)
        weights /= weights.sum()

        rc = self._risk_contributions(weights)
        port_var = float(weights @ self.cov @ weights)

        return RiskParityResult(
            weights={self.asset_ids[i]: float(weights[i]) for i in range(self.n)},
            risk_contributions={self.asset_ids[i]: float(rc[i]) for i in range(self.n)},
            portfolio_volatility=float(np.sqrt(max(port_var, 0))),
            max_risk_contribution=float(rc.max()),
            min_risk_contribution=float(rc.min()),
            gini_coefficient=self._gini(rc),
        )

    @staticmethod
    def _gini(rc: np.ndarray) -> float:
        """Gini coefficient of risk contributions (0=equal, 1=unequal)."""
        if rc.sum() == 0:
            return 0.0
        rc_sorted = np.sort(rc / rc.sum())
        n = len(rc_sorted)
        cumsum = np.cumsum(rc_sorted)
        return float(1 - 2 * cumsum.mean() + (n + 1) / n)

    def budget_allocation(
        self,
        risk_budgets: Dict[str, float],  # asset_id -> desired risk fraction (sum=1)
    ) -> RiskParityResult:
        """
        Risk budgeting: each asset gets a specified risk fraction.
        Extends risk parity to non-equal budgets.
        """
        budgets = np.array([risk_budgets.get(aid, 1.0/self.n) for aid in self.asset_ids])
        budgets /= budgets.sum()

        def objective(w: np.ndarray) -> float:
            rc = self._risk_contributions(w)
            total_rc = rc.sum()
            if total_rc == 0:
                return 0.0
            return float(np.sum((rc / total_rc - budgets) ** 2))

        w0 = np.ones(self.n) / self.n
        constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        bounds = [(0.001, 1.0)] * self.n

        result = minimize(objective, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        weights = result.x if result.success else w0
        weights = np.maximum(weights, 0.0)
        weights /= weights.sum()

        rc = self._risk_contributions(weights)
        return RiskParityResult(
            weights={self.asset_ids[i]: float(weights[i]) for i in range(self.n)},
            risk_contributions={self.asset_ids[i]: float(rc[i]) for i in range(self.n)},
            portfolio_volatility=float(np.sqrt(float(weights @ self.cov @ weights))),
            max_risk_contribution=float(rc.max()),
            min_risk_contribution=float(rc.min()),
            gini_coefficient=self._gini(rc),
        )
