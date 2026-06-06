"""
Capacity expansion planning for VPP portfolio growth.

Uses multi-period LP optimization to determine optimal technology
mix and investment timing to maximize NPV subject to reliability
and budget constraints.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
from scipy.optimize import linprog


@dataclass
class ExpansionTechnology:
    tech_id: str
    name: str
    capacity_mw: float
    capex_usd_kw: float
    annual_opex_usd_kw: float
    annual_revenue_usd_kw: float    # Expected annual revenue per kW
    lifetime_years: int
    lead_time_years: float
    max_buildable_mw_year: float


@dataclass
class ExpansionResult:
    tech_id: str
    build_mw: float
    total_capex_usd: float
    npv_usd: float
    irr: float
    payback_years: float


@dataclass
class ExpansionPlan:
    investments: List[ExpansionResult]
    total_new_capacity_mw: float
    total_capex_usd: float
    portfolio_npv_usd: float


class CapacityExpansionPlanner:
    """
    Multi-year capacity expansion optimizer using LP formulation.

    Objective: Maximize NPV of new investment decisions
    subject to budget, reliability, and build rate constraints.
    """

    def __init__(
        self,
        planning_horizon_years: int = 10,
        discount_rate: float = 0.08,
        annual_budget_usd: float = 50_000_000.0,
        reliability_target_mw: float = 100.0,
    ) -> None:
        self.horizon = planning_horizon_years
        self.discount_rate = discount_rate
        self.budget = annual_budget_usd
        self.reliability_target = reliability_target_mw

    def compute_npv(self, tech: ExpansionTechnology, build_mw: float) -> float:
        """Compute NPV for a given technology at specified build level."""
        capex = tech.capex_usd_kw * build_mw * 1000
        annual_cashflow = (tech.annual_revenue_usd_kw - tech.annual_opex_usd_kw) * build_mw * 1000
        npv = -capex
        for y in range(1, min(tech.lifetime_years, self.horizon) + 1):
            npv += annual_cashflow / (1 + self.discount_rate) ** y
        return npv

    def compute_irr(self, tech: ExpansionTechnology, build_mw: float) -> float:
        """IRR via bisection (Newton-Raphson would also work)."""
        capex = tech.capex_usd_kw * build_mw * 1000
        annual = (tech.annual_revenue_usd_kw - tech.annual_opex_usd_kw) * build_mw * 1000

        def npv_at_rate(r: float) -> float:
            return -capex + sum(annual / (1 + r) ** y for y in range(1, tech.lifetime_years + 1))

        lo, hi = 0.0, 10.0
        for _ in range(50):
            mid = (lo + hi) / 2
            if npv_at_rate(mid) > 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def optimize(self, technologies: List[ExpansionTechnology]) -> ExpansionPlan:
        """
        LP to find optimal investment portfolio.

        Variables: x_i = build level in MW for each technology.
        Objective: maximize sum NPV_i(x_i) = max -c^T x (linprog minimizes)
        Constraints:
        - Budget: sum capex_i * x_i <= budget
        - Reliability: sum x_i >= target
        - Build rate: 0 <= x_i <= max_buildable
        """
        n = len(technologies)
        if n == 0:
            return ExpansionPlan([], 0.0, 0.0, 0.0)

        # Objective: -NPV per MW (linprog minimizes)
        c = []
        for tech in technologies:
            npv_per_mw = self.compute_npv(tech, 1.0)   # NPV per MW
            c.append(-npv_per_mw)

        # Budget constraint: sum capex_i * x_i <= budget
        A_ub = [[tech.capex_usd_kw * 1000 for tech in technologies]]
        b_ub = [self.budget]

        # Reliability constraint: sum x_i >= target (flip sign)
        A_ub.append([-1.0 for _ in technologies])
        b_ub.append(-self.reliability_target)

        bounds = [(0, tech.max_buildable_mw_year) for tech in technologies]

        result = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")

        investments: List[ExpansionResult] = []
        if result.success:
            for tech, build_mw in zip(technologies, result.x):
                if build_mw > 0.01:
                    investments.append(ExpansionResult(
                        tech_id=tech.tech_id,
                        build_mw=float(build_mw),
                        total_capex_usd=tech.capex_usd_kw * build_mw * 1000,
                        npv_usd=self.compute_npv(tech, build_mw),
                        irr=self.compute_irr(tech, build_mw),
                        payback_years=(tech.capex_usd_kw
                                       / max(tech.annual_revenue_usd_kw - tech.annual_opex_usd_kw, 1e-9)),
                    ))

        return ExpansionPlan(
            investments=investments,
            total_new_capacity_mw=sum(i.build_mw for i in investments),
            total_capex_usd=sum(i.total_capex_usd for i in investments),
            portfolio_npv_usd=sum(i.npv_usd for i in investments),
        )
