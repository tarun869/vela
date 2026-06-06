"""
Risk measures: CVaR, VaR, Expected Shortfall, and related portfolio risk metrics.

Implements coherent and non-coherent risk measures per Artzner et al. (1999)
and Rockafellar-Uryasev (2000) CVaR formulation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy import stats


@dataclass
class RiskReport:
    confidence_level: float
    var_usd: float           # Value at Risk (loss threshold)
    cvar_usd: float          # Conditional VaR (Expected Shortfall)
    expected_shortfall: float  # Same as CVaR, alias
    mean_revenue: float
    std_revenue: float
    skewness: float
    kurtosis: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float


def value_at_risk(
    returns: np.ndarray,
    confidence: float = 0.95,
    method: str = "historical",
) -> float:
    """
    Compute Value at Risk (VaR) — the loss not exceeded at given confidence level.

    Args:
        returns: Array of P&L or revenue values.
        confidence: Confidence level (e.g., 0.95 for 95% VaR).
        method: "historical", "parametric", or "cornish_fisher".

    Returns:
        VaR as a positive loss number.
    """
    if len(returns) == 0:
        return 0.0

    if method == "historical":
        var = -np.percentile(returns, (1 - confidence) * 100)
    elif method == "parametric":
        mu, sigma = returns.mean(), returns.std()
        z = stats.norm.ppf(1 - confidence)
        var = -(mu + z * sigma)
    elif method == "cornish_fisher":
        # Cornish-Fisher expansion for non-normal distributions
        mu, sigma = returns.mean(), returns.std()
        skew = float(stats.skew(returns))
        kurt = float(stats.kurtosis(returns))
        z_base = stats.norm.ppf(1 - confidence)
        z_cf = (z_base
                + (z_base**2 - 1) * skew / 6
                + (z_base**3 - 3 * z_base) * kurt / 24
                - (2 * z_base**3 - 5 * z_base) * skew**2 / 36)
        var = -(mu + z_cf * sigma)
    else:
        raise ValueError(f"Unknown method: {method}")

    return float(max(0.0, var))


def conditional_var(
    returns: np.ndarray,
    confidence: float = 0.95,
    method: str = "historical",
) -> float:
    """
    Compute Conditional Value at Risk (CVaR / Expected Shortfall).

    CVaR = E[loss | loss > VaR]

    Returns:
        CVaR as positive loss number.
    """
    if len(returns) == 0:
        return 0.0

    if method == "historical":
        cutoff = np.percentile(returns, (1 - confidence) * 100)
        tail = returns[returns <= cutoff]
        cvar = -float(tail.mean()) if len(tail) > 0 else 0.0
    elif method == "parametric":
        mu, sigma = returns.mean(), returns.std()
        z = stats.norm.ppf(1 - confidence)
        pdf_z = stats.norm.pdf(z)
        cvar = -(mu - sigma * pdf_z / (1 - confidence))
    else:
        # Fall back to historical
        return conditional_var(returns, confidence, "historical")

    return float(max(0.0, cvar))


def max_drawdown(equity_curve: np.ndarray) -> float:
    """
    Compute maximum drawdown from peak to trough.

    Returns:
        Maximum drawdown as a positive fraction.
    """
    if len(equity_curve) < 2:
        return 0.0
    peak = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - peak) / np.where(peak != 0, peak, 1.0)
    return float(-drawdown.min())


def sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.05, periods_per_year: int = 8760) -> float:
    """Annualized Sharpe ratio."""
    if returns.std() == 0:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    return float(excess.mean() / excess.std() * math.sqrt(periods_per_year))


def sortino_ratio(returns: np.ndarray, risk_free_rate: float = 0.05, periods_per_year: int = 8760) -> float:
    """Sortino ratio — uses downside deviation instead of total std."""
    target = risk_free_rate / periods_per_year
    downside = returns[returns < target]
    if len(downside) == 0:
        return float("inf")
    downside_std = np.sqrt(np.mean((downside - target) ** 2))
    if downside_std == 0:
        return float("inf")
    excess_mean = returns.mean() - target
    return float(excess_mean / downside_std * math.sqrt(periods_per_year))


def compute_risk_report(
    revenue_distribution: np.ndarray,
    confidence: float = 0.95,
    risk_free_rate: float = 0.05,
) -> RiskReport:
    """
    Compute comprehensive risk report for a revenue distribution.

    Args:
        revenue_distribution: Array of simulated revenue values.
        confidence: VaR/CVaR confidence level.
        risk_free_rate: Annual risk-free rate.

    Returns:
        RiskReport with all risk metrics.
    """
    r = revenue_distribution
    var = value_at_risk(r, confidence)
    cvar = conditional_var(r, confidence)
    equity = np.cumsum(r)

    return RiskReport(
        confidence_level=confidence,
        var_usd=var,
        cvar_usd=cvar,
        expected_shortfall=cvar,
        mean_revenue=float(r.mean()),
        std_revenue=float(r.std()),
        skewness=float(stats.skew(r)),
        kurtosis=float(stats.kurtosis(r)),
        max_drawdown=max_drawdown(equity),
        sharpe_ratio=sharpe_ratio(r, risk_free_rate),
        sortino_ratio=sortino_ratio(r, risk_free_rate),
    )


class RiskBudgetAllocator:
    """
    Allocates risk budget across VPP assets using CVaR decomposition.
    """

    def __init__(self, confidence: float = 0.95) -> None:
        self.confidence = confidence

    def marginal_cvar(
        self,
        portfolio_returns: np.ndarray,
        asset_returns: np.ndarray,
    ) -> float:
        """
        Marginal CVaR contribution of an asset to portfolio CVaR.

        Returns:
            Marginal CVaR ($/unit weight).
        """
        cutoff = np.percentile(portfolio_returns, (1 - self.confidence) * 100)
        tail_mask = portfolio_returns <= cutoff
        if tail_mask.sum() == 0:
            return 0.0
        return -float(asset_returns[tail_mask].mean())

    def risk_parity_weights(
        self,
        asset_returns_matrix: np.ndarray,   # Shape (n_scenarios, n_assets)
    ) -> np.ndarray:
        """
        Compute equal risk contribution weights.

        Returns:
            Weight vector summing to 1.
        """
        n_assets = asset_returns_matrix.shape[1]
        weights = np.ones(n_assets) / n_assets

        for _ in range(100):
            portfolio = asset_returns_matrix @ weights
            marginals = np.array([
                self.marginal_cvar(portfolio, asset_returns_matrix[:, i])
                for i in range(n_assets)
            ])
            risk_contribs = weights * marginals
            avg_contrib = risk_contribs.mean()
            if avg_contrib == 0:
                break
            # Gradient step toward equal risk
            weights = weights * (avg_contrib / np.where(marginals != 0, marginals, avg_contrib))
            weights = np.maximum(weights, 0.0)
            total = weights.sum()
            if total > 0:
                weights /= total

        return weights
