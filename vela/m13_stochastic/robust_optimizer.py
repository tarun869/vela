"""
Robust optimization: min-max regret formulation for VPP dispatch under uncertainty.

Finds a dispatch strategy that minimizes worst-case regret across
a finite set of scenarios. Uses linear programming via scipy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import linprog


@dataclass
class RobustOptimizationProblem:
    """
    Min-max regret dispatch problem.

    Variables: x[t] = dispatch power (MW) at each period t.
    Objective: minimize max_s { R*(s) - R(x, s) }
        where R*(s) = optimal revenue in scenario s,
              R(x, s) = revenue of dispatch x in scenario s.

    Constraints:
        x_min <= x[t] <= x_max for all t
        ramp_down <= x[t] - x[t-1] <= ramp_up
        sum(x[t] * dt) <= energy_capacity (battery constraint)
    """
    n_periods: int
    n_scenarios: int
    price_scenarios: np.ndarray     # Shape (n_scenarios, n_periods) $/MWh
    scenario_probs: np.ndarray      # Shape (n_scenarios,) probabilities
    x_min: float = 0.0              # Min dispatch (MW)
    x_max: float = 10.0             # Max dispatch (MW)
    ramp_rate: float = 5.0          # MW/period ramp limit
    energy_cap_mwh: float = 40.0    # Total energy budget (MWh)
    dt_h: float = 1.0               # Time step (hours)


@dataclass
class RobustSolution:
    dispatch_mw: np.ndarray         # Optimal dispatch per period
    worst_case_regret_usd: float
    expected_regret_usd: float
    scenario_revenues_usd: np.ndarray
    scenario_regrets_usd: np.ndarray
    optimal_scenario_revenues_usd: np.ndarray


class RobustOptimizer:
    """
    Min-max regret robust optimizer for VPP hourly dispatch.

    Formulates as LP:
      min  z
      s.t. z >= R*(s) - R(x, s)  for all s
           x_min <= x[t] <= x_max
           ramp constraints
           energy constraints
    """

    def __init__(self, problem: RobustOptimizationProblem) -> None:
        self.problem = problem

    def _compute_optimal_revenues(self) -> np.ndarray:
        """
        For each scenario, compute optimal (clairvoyant) revenue.

        Clairvoyant policy: dispatch x_max when price > 0, x_min otherwise.
        """
        p = self.problem
        opt_rev = np.zeros(p.n_scenarios)
        for s in range(p.n_scenarios):
            prices = p.price_scenarios[s]
            dispatch = np.where(prices > 0, p.x_max, p.x_min)
            # Apply energy cap greedily
            energy_used = 0.0
            for t in range(p.n_periods):
                available = min(dispatch[t], max(0, (p.energy_cap_mwh - energy_used) / p.dt_h))
                dispatch[t] = available
                energy_used += available * p.dt_h
            opt_rev[s] = float((dispatch * prices * p.dt_h).sum())
        return opt_rev

    def _revenue_of_dispatch(self, dispatch: np.ndarray) -> np.ndarray:
        """Compute revenue for given dispatch in each scenario."""
        return (self.problem.price_scenarios * dispatch[np.newaxis, :] * self.problem.dt_h).sum(axis=1)

    def solve(self) -> RobustSolution:
        """
        Solve min-max regret problem via linear programming.

        LP variables: [x_0, ..., x_{T-1}, z]
          where z = worst-case regret.

        Returns:
            RobustSolution with optimal dispatch and regret metrics.
        """
        p = self.problem
        T = p.n_periods
        S = p.n_scenarios
        n_vars = T + 1  # x[0..T-1] + z

        opt_rev = self._compute_optimal_revenues()

        # Objective: minimize z (last variable)
        c = np.zeros(n_vars)
        c[-1] = 1.0

        # Inequality constraints: z >= R*(s) - R(x, s)
        # => -sum_t(price[s,t] * dt * x[t]) + z >= R*(s) - 0
        # => [-prices[s,:]*dt, 1] @ [x, z] >= R*(s)
        A_ub = np.zeros((S, n_vars))
        b_ub = np.zeros(S)
        for s in range(S):
            A_ub[s, :T] = -p.price_scenarios[s] * p.dt_h
            A_ub[s, -1] = 1.0
            b_ub[s] = opt_rev[s]

        # Ramp constraints: -ramp <= x[t] - x[t-1] <= ramp
        A_ramp = np.zeros((2 * (T - 1), n_vars))
        b_ramp = np.zeros(2 * (T - 1))
        for t in range(1, T):
            # x[t] - x[t-1] <= ramp_up
            A_ramp[2*(t-1), t] = 1.0
            A_ramp[2*(t-1), t-1] = -1.0
            b_ramp[2*(t-1)] = p.ramp_rate
            # x[t-1] - x[t] <= ramp_down
            A_ramp[2*(t-1)+1, t-1] = 1.0
            A_ramp[2*(t-1)+1, t] = -1.0
            b_ramp[2*(t-1)+1] = p.ramp_rate

        # Energy constraint: sum(x * dt) <= energy_cap
        A_energy = np.zeros((1, n_vars))
        A_energy[0, :T] = p.dt_h
        b_energy = np.array([p.energy_cap_mwh])

        A_ub_full = np.vstack([A_ub, A_ramp, A_energy])
        b_ub_full = np.concatenate([b_ub, b_ramp, b_energy])

        # Variable bounds
        bounds = [(p.x_min, p.x_max)] * T + [(0, None)]  # z >= 0

        result = linprog(c, A_ub=A_ub_full, b_ub=b_ub_full, bounds=bounds, method="highs")

        if not result.success:
            # Fall back to uniform dispatch
            dispatch = np.full(T, (p.x_min + p.x_max) / 2.0)
        else:
            dispatch = result.x[:T]

        scenario_revs = self._revenue_of_dispatch(dispatch)
        regrets = opt_rev - scenario_revs

        return RobustSolution(
            dispatch_mw=dispatch,
            worst_case_regret_usd=float(regrets.max()),
            expected_regret_usd=float((regrets * p.scenario_probs).sum()),
            scenario_revenues_usd=scenario_revs,
            scenario_regrets_usd=regrets,
            optimal_scenario_revenues_usd=opt_rev,
        )
