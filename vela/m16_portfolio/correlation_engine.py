"""
Revenue correlation analysis across VPP sites and market services.

Computes correlation matrices, identifies diversification opportunities,
and measures systemic vs. idiosyncratic risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy import stats


@dataclass
class CorrelationReport:
    correlation_matrix: np.ndarray
    asset_ids: List[str]
    eigenvalues: np.ndarray
    effective_n_factors: float   # Effective number of independent factors
    max_correlation: float
    min_correlation: float
    avg_pairwise_correlation: float
    systemic_variance_fraction: float  # Fraction explained by first factor


class CorrelationEngine:
    """
    Analyzes revenue correlations across VPP portfolio sites.

    Uses Pearson, Spearman, and Kendall correlations plus
    PCA-based factor analysis.
    """

    def __init__(self, asset_ids: List[str]) -> None:
        self.asset_ids = asset_ids
        self.n = len(asset_ids)
        self._revenue_matrix: Optional[np.ndarray] = None  # (T, n_assets)

    def load_revenue_data(self, revenue_matrix: np.ndarray) -> None:
        """
        Load historical revenue data.

        Args:
            revenue_matrix: Shape (n_periods, n_assets), $/MWh or $/hour.
        """
        assert revenue_matrix.shape[1] == self.n
        self._revenue_matrix = revenue_matrix

    def pearson_correlation(self) -> np.ndarray:
        """Compute Pearson correlation matrix."""
        if self._revenue_matrix is None:
            return np.eye(self.n)
        return np.corrcoef(self._revenue_matrix.T)

    def spearman_correlation(self) -> np.ndarray:
        """Compute Spearman rank correlation matrix."""
        if self._revenue_matrix is None:
            return np.eye(self.n)
        n = self.n
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                r, _ = stats.spearmanr(self._revenue_matrix[:, i], self._revenue_matrix[:, j])
                corr[i, j] = corr[j, i] = float(r)
        return corr

    def rolling_correlation(
        self, asset_a: str, asset_b: str, window: int = 90
    ) -> np.ndarray:
        """
        Compute rolling correlation between two assets.

        Returns:
            Array of rolling correlations (length = n_periods - window + 1).
        """
        ia = self.asset_ids.index(asset_a)
        ib = self.asset_ids.index(asset_b)
        ra = self._revenue_matrix[:, ia]
        rb = self._revenue_matrix[:, ib]

        rolling_corr = []
        for t in range(window - 1, len(ra)):
            r, _ = stats.pearsonr(ra[t-window+1:t+1], rb[t-window+1:t+1])
            rolling_corr.append(float(r))
        return np.array(rolling_corr)

    def analyze(self, method: str = "pearson") -> CorrelationReport:
        """
        Generate comprehensive correlation report.

        Args:
            method: "pearson", "spearman".

        Returns:
            CorrelationReport with eigenvalue decomposition.
        """
        if method == "spearman":
            corr = self.spearman_correlation()
        else:
            corr = self.pearson_correlation()

        # PCA on correlation matrix
        eigvals = np.linalg.eigvalsh(corr)
        eigvals = np.sort(eigvals)[::-1]  # Descending

        # Effective number of factors (inverse participation ratio)
        eigvals_pos = eigvals[eigvals > 0]
        n_eff = (eigvals_pos.sum() ** 2) / (eigvals_pos ** 2).sum() if len(eigvals_pos) > 0 else 1.0

        # Off-diagonal correlations
        mask = ~np.eye(self.n, dtype=bool)
        off_diag = corr[mask]

        systemic_frac = float(eigvals[0]) / self.n if self.n > 0 else 0.0

        return CorrelationReport(
            correlation_matrix=corr,
            asset_ids=self.asset_ids,
            eigenvalues=eigvals,
            effective_n_factors=float(n_eff),
            max_correlation=float(off_diag.max()) if len(off_diag) > 0 else 0.0,
            min_correlation=float(off_diag.min()) if len(off_diag) > 0 else 0.0,
            avg_pairwise_correlation=float(off_diag.mean()) if len(off_diag) > 0 else 0.0,
            systemic_variance_fraction=systemic_frac,
        )

    def diversification_benefit(self, weights: np.ndarray) -> float:
        """
        Compute diversification benefit as variance reduction vs equal volatility.

        Returns:
            Fraction of variance reduction from diversification (0–1).
        """
        if self._revenue_matrix is None:
            return 0.0
        stds = self._revenue_matrix.std(axis=0)
        corr = self.pearson_correlation()
        cov = corr * np.outer(stds, stds)

        port_var = float(weights @ cov @ weights)
        weighted_avg_var = float((weights ** 2 @ stds ** 2))

        if weighted_avg_var == 0:
            return 0.0
        return float(1.0 - port_var / weighted_avg_var)

    def cluster_corr_matrix(self, corr: np.ndarray) -> Tuple[np.ndarray, List[int]]:
        """
        Reorder correlation matrix by hierarchical clustering for visualization.

        Returns:
            (reordered_corr, new_order)
        """
        from scipy.cluster.hierarchy import linkage, leaves_list
        dist = 1.0 - np.abs(corr)
        np.fill_diagonal(dist, 0.0)
        Z = linkage(dist[np.triu_indices(self.n, k=1)], method="complete")
        order = list(leaves_list(Z))
        return corr[np.ix_(order, order)], order
