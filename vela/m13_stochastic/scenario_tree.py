"""
Scenario tree generation for stochastic programming.

Builds scenario trees for multi-stage stochastic optimization using:
  - Moment matching (mean, variance, skewness)
  - Fan (non-recombining) tree structure
  - Scenario reduction via Wasserstein distance
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np
from numpy.random import default_rng


@dataclass
class ScenarioNode:
    """A node in the scenario tree."""
    node_id: int
    stage: int
    parent_id: Optional[int]
    probability: float
    values: Dict[str, float]   # e.g., {"price": 45.2, "load": 500.0}
    children: List[int] = field(default_factory=list)


@dataclass
class ScenarioTree:
    """Complete scenario tree for stochastic programming."""
    n_stages: int
    branching_factors: List[int]   # Branches per node at each stage
    nodes: Dict[int, ScenarioNode] = field(default_factory=dict)
    leaf_node_ids: List[int] = field(default_factory=list)

    @property
    def n_scenarios(self) -> int:
        return len(self.leaf_node_ids)

    def get_scenario_path(self, leaf_id: int) -> List[ScenarioNode]:
        """Return the full path from root to leaf for a given leaf node."""
        path: List[ScenarioNode] = []
        node = self.nodes[leaf_id]
        while node is not None:
            path.append(node)
            if node.parent_id is None:
                break
            node = self.nodes[node.parent_id]
        return list(reversed(path))

    def scenario_probability(self, leaf_id: int) -> float:
        """Return marginal probability of a scenario (leaf node)."""
        return self.nodes[leaf_id].probability


class ScenarioTreeBuilder:
    """
    Builds scenario trees from stochastic process parameters.

    Supports:
      - GBM (Geometric Brownian Motion) for prices
      - Mean-reverting Ornstein-Uhlenbeck for load/frequency
      - Correlated multi-variate processes
    """

    def __init__(self, seed: int = 42) -> None:
        self.rng = default_rng(seed)
        self._next_id = 0

    def _new_id(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

    def build_price_tree(
        self,
        n_stages: int,
        branching: int,
        initial_price: float,
        mu: float,           # Drift (annualized)
        sigma: float,        # Volatility (annualized)
        dt: float = 1/8760,  # Time step (years) — default 1 hour
        variable_name: str = "price",
    ) -> ScenarioTree:
        """
        Build a GBM price scenario tree.

        Uses log-normal distribution for price increments.
        """
        branching_factors = [branching] * n_stages
        tree = ScenarioTree(n_stages=n_stages, branching_factors=branching_factors)

        # Root node
        root_id = self._new_id()
        root = ScenarioNode(
            node_id=root_id, stage=0, parent_id=None,
            probability=1.0, values={variable_name: initial_price}
        )
        tree.nodes[root_id] = root
        current_level = [root_id]

        for stage in range(1, n_stages + 1):
            next_level: List[int] = []
            for parent_id in current_level:
                parent = tree.nodes[parent_id]
                p_parent = parent.values[variable_name]
                child_prob = 1.0 / branching

                # GBM increment: dS = S * (mu*dt + sigma*sqrt(dt)*Z)
                z_values = self.rng.standard_normal(branching)
                # Moment-match: adjust Z to have mean=0, std=1
                z_values = (z_values - z_values.mean()) / max(z_values.std(), 1e-9)

                for k in range(branching):
                    price_new = p_parent * np.exp(
                        (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z_values[k]
                    )
                    child_id = self._new_id()
                    child = ScenarioNode(
                        node_id=child_id,
                        stage=stage,
                        parent_id=parent_id,
                        probability=parent.probability * child_prob,
                        values={variable_name: float(max(0.01, price_new))},
                    )
                    tree.nodes[child_id] = child
                    parent.children.append(child_id)
                    next_level.append(child_id)

            current_level = next_level

        tree.leaf_node_ids = current_level
        return tree

    def build_multivariate_tree(
        self,
        n_stages: int,
        branching: int,
        initial_values: Dict[str, float],
        means: Dict[str, float],
        sigmas: Dict[str, float],
        correlation_matrix: Optional[np.ndarray] = None,
        dt: float = 1/8760,
    ) -> ScenarioTree:
        """
        Build a multi-variate scenario tree with correlated processes.
        """
        variables = list(initial_values.keys())
        n_vars = len(variables)

        if correlation_matrix is None:
            correlation_matrix = np.eye(n_vars)

        # Cholesky decomposition for correlated samples
        L = np.linalg.cholesky(correlation_matrix)

        branching_factors = [branching] * n_stages
        tree = ScenarioTree(n_stages=n_stages, branching_factors=branching_factors)

        root_id = self._new_id()
        root = ScenarioNode(
            node_id=root_id, stage=0, parent_id=None,
            probability=1.0, values=dict(initial_values)
        )
        tree.nodes[root_id] = root
        current_level = [root_id]

        for stage in range(1, n_stages + 1):
            next_level: List[int] = []
            for parent_id in current_level:
                parent = tree.nodes[parent_id]
                child_prob = 1.0 / branching

                # Generate correlated normal samples
                Z_raw = self.rng.standard_normal((n_vars, branching))
                Z_raw = (Z_raw - Z_raw.mean(axis=1, keepdims=True))
                Z_corr = L @ Z_raw  # (n_vars, branching)

                for k in range(branching):
                    new_values: Dict[str, float] = {}
                    for vi, var in enumerate(variables):
                        mu_v = means[var]
                        sig_v = sigmas[var]
                        drift = mu_v * dt
                        shock = sig_v * np.sqrt(dt) * Z_corr[vi, k]
                        new_values[var] = max(0.0, parent.values[var] + drift + shock)

                    child_id = self._new_id()
                    child = ScenarioNode(
                        node_id=child_id,
                        stage=stage,
                        parent_id=parent_id,
                        probability=parent.probability * child_prob,
                        values=new_values,
                    )
                    tree.nodes[child_id] = child
                    parent.children.append(child_id)
                    next_level.append(child_id)

            current_level = next_level

        tree.leaf_node_ids = current_level
        return tree

    def reduce_scenarios(
        self,
        tree: ScenarioTree,
        target_count: int,
        variable: str = "price",
    ) -> ScenarioTree:
        """
        Reduce scenario count using backward reduction (Wasserstein distance).

        Iteratively removes the scenario with smallest weighted distance
        to the remaining set and redistributes its probability.
        """
        leaf_ids = list(tree.leaf_node_ids)
        probs = {lid: tree.nodes[lid].probability for lid in leaf_ids}
        values = {lid: tree.nodes[lid].values.get(variable, 0.0) for lid in leaf_ids}

        while len(leaf_ids) > target_count:
            # Find scenario with minimum Wasserstein contribution
            min_cost = float("inf")
            remove_id = None
            nearest_id = None

            for i, lid in enumerate(leaf_ids):
                # Cost = prob_i * min distance to other scenarios
                distances = [
                    abs(values[lid] - values[other]) * probs[other]
                    for other in leaf_ids if other != lid
                ]
                if distances:
                    cost = probs[lid] * min(distances)
                    if cost < min_cost:
                        min_cost = cost
                        remove_id = lid
                        nearest_id = min(
                            (other for other in leaf_ids if other != lid),
                            key=lambda x: abs(values[x] - values[lid])
                        )

            if remove_id is None:
                break

            # Redistribute probability
            probs[nearest_id] += probs[remove_id]
            leaf_ids.remove(remove_id)
            del probs[remove_id]

        # Rebuild reduced tree
        reduced = ScenarioTree(n_stages=tree.n_stages, branching_factors=tree.branching_factors)
        for lid in leaf_ids:
            node = tree.nodes[lid]
            node.probability = probs[lid]
            reduced.nodes[lid] = node
        reduced.leaf_node_ids = leaf_ids
        return reduced
