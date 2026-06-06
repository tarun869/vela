"""
Site clustering by behavioral pattern using k-means and hierarchical clustering.

Groups VPP sites by revenue profile, dispatch behavior, and market participation
to identify substitutable assets and correlated risk groups.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.spatial.distance import cdist
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram


@dataclass
class SiteFeatures:
    site_id: str
    avg_revenue_usd_year: float
    revenue_volatility: float
    peak_dispatch_fraction: float   # Fraction of dispatch at peak hours
    market_services: List[str]      # e.g., ["energy", "regulation", "spinning"]
    capacity_mw: float
    utilization_factor: float       # Average utilization
    location_region: str
    asset_class: str


@dataclass
class SiteCluster:
    cluster_id: int
    site_ids: List[str]
    centroid: np.ndarray
    intra_cluster_distance: float   # Average pairwise distance within cluster
    silhouette_score: float


class SiteClusterer:
    """
    Clusters VPP sites into behavioral groups using k-means and hierarchical methods.

    Features are normalized before clustering.
    """

    def __init__(self, sites: List[SiteFeatures]) -> None:
        self.sites = sites
        self.n = len(sites)
        self._feature_matrix: Optional[np.ndarray] = None
        self._feature_means: Optional[np.ndarray] = None
        self._feature_stds: Optional[np.ndarray] = None

    def _build_features(self) -> np.ndarray:
        """Build numerical feature matrix from SiteFeatures."""
        features = []
        for s in self.sites:
            row = [
                s.avg_revenue_usd_year,
                s.revenue_volatility,
                s.peak_dispatch_fraction,
                s.capacity_mw,
                s.utilization_factor,
                float(len(s.market_services)),  # Count of services
            ]
            features.append(row)
        return np.array(features, dtype=float)

    def _normalize(self, X: np.ndarray) -> np.ndarray:
        self._feature_means = X.mean(axis=0)
        self._feature_stds = np.where(X.std(axis=0) > 0, X.std(axis=0), 1.0)
        return (X - self._feature_means) / self._feature_stds

    def kmeans(self, k: int, n_init: int = 10, max_iter: int = 300) -> List[SiteCluster]:
        """
        K-means clustering with k-means++ initialization.

        Returns:
            List of SiteCluster objects.
        """
        if self._feature_matrix is None:
            X_raw = self._build_features()
            self._feature_matrix = self._normalize(X_raw)

        X = self._feature_matrix
        best_inertia = float("inf")
        best_labels = None
        best_centroids = None

        rng = np.random.default_rng(42)

        for _ in range(n_init):
            # K-means++ initialization
            centroids = [X[rng.integers(self.n)]]
            for _ in range(k - 1):
                dists = np.min(cdist(X, np.array(centroids)), axis=1) ** 2
                probs = dists / dists.sum()
                centroids.append(X[rng.choice(self.n, p=probs)])
            centroids = np.array(centroids)

            labels = np.zeros(self.n, dtype=int)
            for iteration in range(max_iter):
                dists = cdist(X, centroids)
                new_labels = np.argmin(dists, axis=1)
                if np.all(new_labels == labels):
                    break
                labels = new_labels
                for j in range(k):
                    mask = labels == j
                    if mask.any():
                        centroids[j] = X[mask].mean(axis=0)

            inertia = sum(
                float(cdist([X[i]], [centroids[labels[i]]])[0, 0]) ** 2
                for i in range(self.n)
            )
            if inertia < best_inertia:
                best_inertia = inertia
                best_labels = labels.copy()
                best_centroids = centroids.copy()

        clusters: List[SiteCluster] = []
        for j in range(k):
            mask = best_labels == j
            site_ids = [self.sites[i].site_id for i in range(self.n) if mask[i]]
            centroid = best_centroids[j]
            points = X[mask]
            if len(points) > 1:
                intra_dist = float(cdist(points, points).mean())
            else:
                intra_dist = 0.0
            silhouette = self._silhouette_score(X, best_labels, j)
            clusters.append(SiteCluster(
                cluster_id=j,
                site_ids=site_ids,
                centroid=centroid,
                intra_cluster_distance=intra_dist,
                silhouette_score=silhouette,
            ))
        return clusters

    def hierarchical(self, k: int, method: str = "ward") -> List[SiteCluster]:
        """Hierarchical clustering using scipy linkage."""
        if self._feature_matrix is None:
            X_raw = self._build_features()
            self._feature_matrix = self._normalize(X_raw)

        X = self._feature_matrix
        Z = linkage(X, method=method)
        labels = fcluster(Z, k, criterion="maxclust") - 1

        clusters: List[SiteCluster] = []
        for j in range(k):
            mask = labels == j
            site_ids = [self.sites[i].site_id for i in range(self.n) if mask[i]]
            points = X[mask]
            centroid = points.mean(axis=0) if len(points) > 0 else X.mean(axis=0)
            intra_dist = float(cdist(points, points).mean()) if len(points) > 1 else 0.0
            clusters.append(SiteCluster(
                cluster_id=j,
                site_ids=site_ids,
                centroid=centroid,
                intra_cluster_distance=intra_dist,
                silhouette_score=self._silhouette_score(X, labels, j),
            ))
        return clusters

    def _silhouette_score(self, X: np.ndarray, labels: np.ndarray, cluster_id: int) -> float:
        """Compute average silhouette score for a cluster."""
        mask = labels == cluster_id
        if mask.sum() < 2:
            return 0.0
        cluster_pts = X[mask]
        a_vals = []
        for i, pt in enumerate(cluster_pts):
            others = np.delete(cluster_pts, i, axis=0)
            a = cdist([pt], others).mean() if len(others) > 0 else 0.0
            a_vals.append(a)
        a = float(np.mean(a_vals))

        b_vals = []
        for j in set(labels) - {cluster_id}:
            other_pts = X[labels == j]
            b_vals.append(cdist(cluster_pts, other_pts).mean())
        b = min(b_vals) if b_vals else 0.0

        denom = max(a, b)
        return float((b - a) / denom) if denom > 0 else 0.0

    def optimal_k(self, k_range: range = range(2, 8)) -> Tuple[int, List[float]]:
        """
        Find optimal k using elbow method (within-cluster sum of squares).

        Returns:
            (optimal_k, list_of_wcss_per_k)
        """
        wcss: List[float] = []
        for k in k_range:
            clusters = self.kmeans(k)
            if self._feature_matrix is None:
                break
            total_wcss = sum(c.intra_cluster_distance for c in clusters)
            wcss.append(total_wcss)

        # Elbow: find k where marginal improvement drops below 20%
        optimal_k = list(k_range)[0]
        for i in range(1, len(wcss) - 1):
            improvement = (wcss[i-1] - wcss[i]) / max(wcss[0], 1e-9)
            if improvement < 0.20:
                optimal_k = list(k_range)[i]
                break

        return optimal_k, wcss
