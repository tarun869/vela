"""
Portfolio capacity planning for VPP fleet expansion.

Determines optimal capacity additions, timing, and technology mix
to maximize NPV subject to budget and reliability constraints.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import linprog


@dataclass
class TechnologyOption:
    tech_id: str
    name: str
    capex_per_kw: float          # $/kW installed
    opex_per_kw_year: float      # $/kW/year fixed O&M
    revenue_per_kw_year: float   # Expected annual revenue ($/kW/year)
    lifetime_years: int
    degradation_rate: float = 0.005  # Annual capacity loss (fraction)
    lead_time_years: int = 1         # Construction/deployment time
    min_capacity_kw: float = 0.0
    max_capacity_kw: float = 1e6
    asset_class: str = "storage"


@dataclass
class CapacityExpansionResult:
    additions_kw: Dict[str, List[float]]   # tech_id -> additions per year
    total_capex_usd: float
    npv_usd: float
    irr_pct: float
    payback_years: float
    capacity_by_year: Dict[int, float]     # year -> total capacity (kW)
    cash_flows_usd: List[float]            # Annual net cash flows


class CapacityPlanningOptimizer:
    """
    Linear programming-based capacity expansion model.

    Minimizes total cost (or maximizes NPV) for a multi-year expansion
    plan subject to budget, resource, and reliability targets.
    """

    def __init__(
        self,
        technologies: List[TechnologyOption],
        planning_horizon_years: int = 10,
        discount_rate: float = 0.08,
        annual_budget_usd: Optional[float] = None,
    ) -> None:
        self.technologies = technologies
        self.T = planning_horizon_years
        self.discount_rate = discount_rate
        self.annual_budget = annual_budget_usd or 1e9
        self._n_tech = len(technologies)

    def _npv_factor(self, year: int) -> float:
        return 1.0 / (1 + self.discount_rate) ** year

    def optimize(
        self,
        reliability_target_kw: float = 10000.0,
        total_budget_usd: Optional[float] = None,
    ) -> CapacityExpansionResult:
        """
        Solve capacity expansion LP.

        Decision variables: x[t, i] = capacity added in year t for technology i (kW)

        Objective: maximize NPV = sum_t sum_i x[t,i] * (revenue - opex) * PVF - capex * PVF
        """
        budget = total_budget_usd or self.annual_budget * self.T
        T = self.T
        n = self._n_tech
        n_vars = T * n

        def var_idx(t: int, i: int) -> int:
            return t * n + i

        # Objective: minimize negative NPV
        c = np.zeros(n_vars)
        for t in range(T):
            for i, tech in enumerate(self.technologies):
                # NPV contribution of 1 kW added in year t:
                # - capex paid at year t
                # + (revenue - opex) from year t+lead_time to t+lifetime
                capex_pv = tech.capex_per_kw * self._npv_factor(t)
                rev_pv = sum(
                    (tech.revenue_per_kw_year - tech.opex_per_kw_year)
                    * (1 - tech.degradation_rate) ** (yr - t - tech.lead_time_years)
                    * self._npv_factor(yr)
                    for yr in range(t + tech.lead_time_years, min(t + tech.lifetime_years, T))
                )
                c[var_idx(t, i)] = -(rev_pv - capex_pv)  # negative for minimization

        # Inequality constraints
        A_ub_list = []
        b_ub_list = []

        # Annual budget constraint
        for t in range(T):
            row = np.zeros(n_vars)
            for i, tech in enumerate(self.technologies):
                row[var_idx(t, i)] = tech.capex_per_kw
            A_ub_list.append(row)
            b_ub_list.append(self.annual_budget)

        # Total budget
        row_total = np.zeros(n_vars)
        for t in range(T):
            for i, tech in enumerate(self.technologies):
                row_total[var_idx(t, i)] = tech.capex_per_kw
        A_ub_list.append(row_total)
        b_ub_list.append(budget)

        A_ub = np.array(A_ub_list)
        b_ub = np.array(b_ub_list)

        # Reliability target: cumulative capacity >= target by final year
        # -sum_t,i(x[t,i]) <= -target
        row_rel = np.zeros(n_vars)
        for t in range(T):
            for i in range(n):
                row_rel[var_idx(t, i)] = -1.0
        A_ub = np.vstack([A_ub, row_rel.reshape(1, -1)])
        b_ub = np.append(b_ub, -reliability_target_kw)

        # Variable bounds
        bounds = []
        for t in range(T):
            for i, tech in enumerate(self.technologies):
                bounds.append((tech.min_capacity_kw, tech.max_capacity_kw))

        result = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")

        additions: Dict[str, List[float]] = {tech.tech_id: [0.0] * T for tech in self.technologies}
        total_capex = 0.0

        if result.success:
            for t in range(T):
                for i, tech in enumerate(self.technologies):
                    cap = float(result.x[var_idx(t, i)])
                    additions[tech.tech_id][t] = cap
                    total_capex += cap * tech.capex_per_kw

        # Compute cash flows
        cash_flows = []
        for t in range(T):
            cf = -sum(additions[tech.tech_id][t] * tech.capex_per_kw for tech in self.technologies)
            for yr_add in range(t + 1):
                for tech in self.technologies:
                    cap = additions[tech.tech_id][yr_add]
                    if yr_add + tech.lead_time_years <= t < yr_add + tech.lifetime_years:
                        age = t - yr_add - tech.lead_time_years
                        degrade = (1 - tech.degradation_rate) ** age
                        cf += cap * degrade * (tech.revenue_per_kw_year - tech.opex_per_kw_year)
            cash_flows.append(cf)

        npv = sum(cf * self._npv_factor(t) for t, cf in enumerate(cash_flows))

        # Simple IRR via bisection
        irr = self._compute_irr(cash_flows)

        # Payback
        cumsum = np.cumsum(cash_flows)
        payback = next((t for t, cs in enumerate(cumsum) if cs >= 0), T)

        # Capacity by year
        cap_by_year: Dict[int, float] = {}
        for t in range(T):
            cap_by_year[t] = sum(
                sum(additions[tech.tech_id][:t+1]) for tech in self.technologies
            )

        return CapacityExpansionResult(
            additions_kw=additions,
            total_capex_usd=total_capex,
            npv_usd=npv,
            irr_pct=irr * 100.0,
            payback_years=float(payback),
            capacity_by_year=cap_by_year,
            cash_flows_usd=cash_flows,
        )

    @staticmethod
    def _compute_irr(cash_flows: List[float]) -> float:
        """Compute IRR via bisection on NPV = 0."""
        lo, hi = -0.99, 5.0
        for _ in range(100):
            mid = (lo + hi) / 2.0
            npv = sum(cf / (1 + mid) ** t for t, cf in enumerate(cash_flows))
            if abs(npv) < 1.0:
                return mid
            if npv > 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0
