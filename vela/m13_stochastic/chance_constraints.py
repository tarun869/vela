"""
Chance-constrained programming for VPP dispatch under uncertainty.

Implements chance constraints of the form:
  P(g(x, xi) <= 0) >= 1 - epsilon

using:
  - Sample average approximation (SAA)
  - Deterministic equivalent via Gaussian approximation
  - Conditional Value-at-Risk (CVaR) conservative approximation
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
import numpy as np
from scipy import stats
from scipy.optimize import minimize, LinearConstraint, Bounds


@dataclass
class ChanceConstraintSpec:
    """
    Specification of a single chance constraint.

    P(f(x, xi) <= rhs) >= 1 - epsilon
    """
    name: str
    epsilon: float               # Violation probability tolerance (e.g., 0.05)
    rhs: float                   # Right-hand side of constraint
    use_cvar_approximation: bool = True  # Tighter but conservative


class ChanceConstrainedOptimizer:
    """
    Solves a chance-constrained VPP dispatch optimization problem.

    Problem:
        max  E[revenue(x, xi)]
        s.t. P(constraint_i(x, xi) <= 0) >= 1 - epsilon_i   for all i
             x_lb <= x <= x_ub

    Solution approach: SAA with big-M binary reformulation approximation
    (here simplified to CVaR surrogate for tractability).
    """

    def __init__(
        self,
        n_periods: int,
        x_lb: np.ndarray,
        x_ub: np.ndarray,
        dt_h: float = 1.0,
    ) -> None:
        self.n_periods = n_periods
        self.x_lb = x_lb
        self.x_ub = x_ub
        self.dt_h = dt_h

    def _cvar_constraint(
        self,
        x: np.ndarray,
        xi_samples: np.ndarray,   # Shape (n_samples, n_periods) or (n_samples,)
        g_fn: Callable,           # g(x, xi) — constraint function, should be <= 0
        epsilon: float,
    ) -> float:
        """
        CVaR conservative approximation to chance constraint.

        CVaR_{1-epsilon}[g(x, xi)] <= 0 implies P(g <= 0) >= 1 - epsilon.

        Returns:
            CVaR value (positive means constraint violated).
        """
        n_samples = len(xi_samples)
        g_values = np.array([g_fn(x, xi_samples[i]) for i in range(n_samples)])

        cutoff_idx = int(np.ceil((1 - epsilon) * n_samples))
        sorted_g = np.sort(g_values)
        var_val = sorted_g[min(cutoff_idx, n_samples - 1)]
        tail = sorted_g[cutoff_idx:]
        cvar = float(tail.mean()) if len(tail) > 0 else var_val
        return cvar

    def optimize_saa(
        self,
        price_scenarios: np.ndarray,    # (n_samples, n_periods) $/MWh
        constraint_scenarios: np.ndarray,  # (n_samples, n_periods)
        chance_constraints: List[ChanceConstraintSpec],
        n_iterations: int = 50,
    ) -> Tuple[np.ndarray, float, bool]:
        """
        Sample Average Approximation (SAA) optimization.

        Solves deterministic equivalent using sampled scenarios.

        Returns:
            (optimal_dispatch, expected_revenue, constraint_satisfied)
        """
        T = self.n_periods
        n_samples = len(price_scenarios)

        def objective(x: np.ndarray) -> float:
            # Expected revenue (negative for minimization)
            rev = -(price_scenarios * x[np.newaxis, :] * self.dt_h).sum(axis=1).mean()
            return rev

        def obj_grad(x: np.ndarray) -> np.ndarray:
            return -(price_scenarios * self.dt_h).mean(axis=0)

        # Build CVaR constraints
        scipy_constraints = []
        for spec in chance_constraints:
            def make_cvar_constr(spec_inner):
                def cvar_constr(x):
                    g_vals = constraint_scenarios @ x - spec_inner.rhs
                    cutoff = int(np.ceil((1 - spec_inner.epsilon) * n_samples))
                    sorted_g = np.sort(g_vals)
                    tail = sorted_g[min(cutoff, n_samples-1):]
                    cvar = float(tail.mean()) if len(tail) > 0 else sorted_g[-1]
                    return -cvar  # >= 0 means CVaR <= 0
                return cvar_constr
            scipy_constraints.append({"type": "ineq", "fun": make_cvar_constr(spec)})

        bounds = Bounds(lb=self.x_lb, ub=self.x_ub)
        x0 = (self.x_lb + self.x_ub) / 2.0

        result = minimize(
            objective,
            x0,
            jac=obj_grad,
            method="SLSQP",
            bounds=bounds,
            constraints=scipy_constraints,
            options={"maxiter": n_iterations, "ftol": 1e-6},
        )

        # Check constraint satisfaction
        satisfied = True
        for spec in chance_constraints:
            g_vals = constraint_scenarios @ result.x - spec.rhs
            violation_prob = (g_vals > 0).mean()
            if violation_prob > spec.epsilon + 0.01:  # 1% tolerance
                satisfied = False

        return result.x, -result.fun, satisfied

    def reliability_constraint(
        self,
        dispatch: np.ndarray,
        capacity_scenarios: np.ndarray,   # (n_samples, n_periods) MW available
        reliability_target: float = 0.99,
    ) -> Tuple[bool, float]:
        """
        Check reliability chance constraint: P(dispatch <= capacity) >= target.

        Returns:
            (constraint_satisfied, actual_reliability)
        """
        n_samples = len(capacity_scenarios)
        satisfied_count = np.all(capacity_scenarios >= dispatch[np.newaxis, :], axis=1).sum()
        reliability = satisfied_count / n_samples
        return reliability >= reliability_target, float(reliability)

    def gaussian_chance_constraint(
        self,
        a: np.ndarray,    # Linear constraint: a @ x + b * xi <= rhs
        b: float,
        mu_xi: float,     # Mean of uncertain parameter xi
        sigma_xi: float,  # Std of uncertain parameter xi
        rhs: float,
        epsilon: float,
    ) -> np.ndarray:
        """
        Deterministic equivalent of Gaussian chance constraint.

        P(a @ x + b * xi <= rhs) >= 1 - epsilon
        => a @ x <= rhs - b * mu_xi - |b| * sigma_xi * Phi^{-1}(1 - epsilon)

        Returns:
            Deterministic constraint coefficients (n_periods,) and RHS.
        """
        z_eps = stats.norm.ppf(1 - epsilon)
        effective_rhs = rhs - b * mu_xi - abs(b) * sigma_xi * z_eps
        return a, effective_rhs
