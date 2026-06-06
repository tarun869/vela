"""
Multi-site portfolio optimizer using mean-variance (Markowitz) framework.

Optimizes allocation of VPP resources across sites to maximize
risk-adjusted returns, subject to operational and regulatory constraints.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import minimize


@dataclass
class PortfolioAsset:
    asset_id: str
    site_id: str
    capacity_mw: float
    expected_annual_revenue_usd: float
    revenue_std_usd: float
    min_allocation: float = 0.0    # Minimum weight
    max_allocation: float = 1.0    # Maximum weight
    asset_class: str = "storage"   # "storage", "solar", "wind", "dr"


@dataclass
class PortfolioResult:
    weights: Dict[str, float]        # asset_id -> weight
    expected_return_usd: float
    portfolio_variance: float
    portfolio_std_usd: float
    sharpe_ratio: float
    diversification_ratio: float
    efficient_frontier: List[Tuple[float, float]]  # (std, return) points


class MeanVarianceOptimizer:
    """
    Markowitz mean-variance portfolio optimization for VPP revenue streams.

    Minimizes portfolio variance subject to a target return,
    or maximizes Sharpe ratio directly.
    """

    def __init__(self, assets: List[PortfolioAsset], risk_free_rate: float = 0.05) -> None:
        self.assets = assets
        self.n = len(assets)
        self.risk_free = risk_free_rate
        self._cov_matrix: Optional[np.ndarray] = None
        self._returns: Optional[np.ndarray] = None

    def set_covariance_matrix(self, cov: np.ndarray) -> None:
        """Set the revenue covariance matrix (n x n)."""
        assert cov.shape == (self.n, self.n), "Covariance matrix must be n x n"
        self._cov_matrix = cov

    def estimate_covariance(self, historical_revenues: np.ndarray) -> np.ndarray:
        """
        Estimate covariance from historical revenue data.

        Args:
            historical_revenues: Shape (n_periods, n_assets).

        Returns:
            Covariance matrix (n x n).
        """
        cov = np.cov(historical_revenues.T)
        self._cov_matrix = cov
        return cov

    def _get_returns(self) -> np.ndarray:
        if self._returns is None:
            self._returns = np.array([a.expected_annual_revenue_usd for a in self.assets])
        return self._returns

    def _get_cov(self) -> np.ndarray:
        if self._cov_matrix is None:
            # Default: diagonal covariance (uncorrelated)
            stds = np.array([a.revenue_std_usd for a in self.assets])
            self._cov_matrix = np.diag(stds ** 2)
        return self._cov_matrix

    def _portfolio_stats(self, weights: np.ndarray) -> Tuple[float, float, float]:
        """Return (expected_return, variance, sharpe) for a weight vector."""
        mu = self._get_returns()
        cov = self._get_cov()
        ret = float(weights @ mu)
        var = float(weights @ cov @ weights)
        std = float(np.sqrt(max(var, 0.0)))
        sharpe = (ret - self.risk_free) / std if std > 1.0 else 0.0
        return ret, var, sharpe

    def maximize_sharpe(self) -> PortfolioResult:
        """Find the maximum Sharpe ratio portfolio."""
        mu = self._get_returns()
        cov = self._get_cov()

        def neg_sharpe(w: np.ndarray) -> float:
            ret = float(w @ mu)
            var = float(w @ cov @ w)
            std = float(np.sqrt(max(var, 1e-9)))
            return -(ret - self.risk_free) / std

        def neg_sharpe_grad(w: np.ndarray) -> np.ndarray:
            ret = float(w @ mu)
            cov_w = cov @ w
            var = float(w @ cov_w)
            std = float(np.sqrt(max(var, 1e-9)))
            sharpe = (ret - self.risk_free) / std
            d_ret = mu
            d_std = cov_w / std
            return -(d_ret / std - sharpe * d_std / std)

        constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        bounds = [(a.min_allocation, a.max_allocation) for a in self.assets]
        w0 = np.ones(self.n) / self.n

        result = minimize(
            neg_sharpe, w0, jac=neg_sharpe_grad,
            method="SLSQP", bounds=bounds, constraints=constraints,
            options={"ftol": 1e-9, "maxiter": 1000}
        )

        weights = result.x if result.success else w0
        weights = np.maximum(weights, 0.0)
        weights /= weights.sum()

        ret, var, sharpe = self._portfolio_stats(weights)
        ef = self._efficient_frontier(n_points=30)

        return PortfolioResult(
            weights={self.assets[i].asset_id: float(weights[i]) for i in range(self.n)},
            expected_return_usd=ret,
            portfolio_variance=var,
            portfolio_std_usd=float(np.sqrt(max(var, 0))),
            sharpe_ratio=sharpe,
            diversification_ratio=self._diversification_ratio(weights),
            efficient_frontier=ef,
        )

    def minimize_variance(self, target_return: Optional[float] = None) -> PortfolioResult:
        """Find the minimum variance portfolio, optionally at a target return."""
        mu = self._get_returns()
        cov = self._get_cov()

        def portfolio_var(w: np.ndarray) -> float:
            return float(w @ cov @ w)

        def var_grad(w: np.ndarray) -> np.ndarray:
            return 2.0 * cov @ w

        constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
        if target_return is not None:
            constraints.append({"type": "eq", "fun": lambda w: float(w @ mu) - target_return})

        bounds = [(a.min_allocation, a.max_allocation) for a in self.assets]
        w0 = np.ones(self.n) / self.n

        result = minimize(
            portfolio_var, w0, jac=var_grad,
            method="SLSQP", bounds=bounds, constraints=constraints,
        )

        weights = result.x if result.success else w0
        weights = np.maximum(weights, 0.0)
        if weights.sum() > 0:
            weights /= weights.sum()

        ret, var, sharpe = self._portfolio_stats(weights)

        return PortfolioResult(
            weights={self.assets[i].asset_id: float(weights[i]) for i in range(self.n)},
            expected_return_usd=ret,
            portfolio_variance=var,
            portfolio_std_usd=float(np.sqrt(max(var, 0))),
            sharpe_ratio=sharpe,
            diversification_ratio=self._diversification_ratio(weights),
            efficient_frontier=self._efficient_frontier(),
        )

    def _diversification_ratio(self, weights: np.ndarray) -> float:
        """Diversification ratio = weighted avg vol / portfolio vol."""
        stds = np.sqrt(np.diag(self._get_cov()))
        weighted_avg_vol = float(weights @ stds)
        port_vol = float(np.sqrt(max(weights @ self._get_cov() @ weights, 1e-9)))
        return weighted_avg_vol / port_vol if port_vol > 0 else 1.0

    def _efficient_frontier(self, n_points: int = 30) -> List[Tuple[float, float]]:
        """Generate efficient frontier points."""
        mu = self._get_returns()
        ret_min = float(mu.min())
        ret_max = float(mu.max())
        targets = np.linspace(ret_min, ret_max, n_points)

        ef_points: List[Tuple[float, float]] = []
        for target in targets:
            result = self.minimize_variance(target_return=float(target))
            ef_points.append((result.portfolio_std_usd, result.expected_return_usd))

        return ef_points
