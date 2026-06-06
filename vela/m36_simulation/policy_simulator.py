"""
Policy simulation for VPP regulatory scenario analysis.

Tests how different market rules, tariff structures, and
incentive regimes affect VPP economics and customer adoption.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List
import numpy as np


@dataclass
class PolicyScenario:
    scenario_id: str
    name: str
    parameters: Dict[str, Any]     # Parameter overrides for this scenario
    description: str = ""


@dataclass
class PolicyResult:
    scenario_id: str
    total_vpp_revenue_usd: float
    fleet_capacity_mw: float
    customer_savings_usd: float
    carbon_reduction_tons: float
    npv_usd: float
    irr: float


class PolicySimulator:
    """
    Simulates VPP performance under different policy assumptions.

    Enables regulatory scenario analysis (e.g., "what if ITC drops from 30% to 10%?")
    by running parameterized financial models across policy scenarios.
    """

    def __init__(
        self,
        baseline_params: Dict[str, float],
        model_fn: Callable[[Dict[str, float]], Dict[str, float]],
    ) -> None:
        """
        Args:
            baseline_params: Default parameter set.
            model_fn: Function taking parameters -> output metrics dict.
        """
        self.baseline = baseline_params
        self.model_fn = model_fn

    def run_scenario(self, scenario: PolicyScenario) -> PolicyResult:
        """Run model with scenario parameter overrides."""
        params = {**self.baseline, **scenario.parameters}
        outputs = self.model_fn(params)
        return PolicyResult(
            scenario_id=scenario.scenario_id,
            total_vpp_revenue_usd=outputs.get("revenue_usd", 0.0),
            fleet_capacity_mw=outputs.get("fleet_mw", 0.0),
            customer_savings_usd=outputs.get("customer_savings_usd", 0.0),
            carbon_reduction_tons=outputs.get("carbon_tons", 0.0),
            npv_usd=outputs.get("npv_usd", 0.0),
            irr=outputs.get("irr", 0.0),
        )

    def compare_scenarios(
        self, scenarios: List[PolicyScenario]
    ) -> Dict[str, PolicyResult]:
        """Run all scenarios and return results keyed by scenario_id."""
        return {s.scenario_id: self.run_scenario(s) for s in scenarios}

    def sensitivity_analysis(
        self,
        parameter: str,
        values: List[float],
        output_key: str = "npv_usd",
    ) -> Dict[float, float]:
        """One-at-a-time sensitivity analysis for a parameter."""
        results: Dict[float, float] = {}
        for val in values:
            params = {**self.baseline, parameter: val}
            outputs = self.model_fn(params)
            results[val] = outputs.get(output_key, 0.0)
        return results


def default_vpp_model(params: Dict[str, float]) -> Dict[str, float]:
    """
    Simple VPP financial model for policy simulation testing.

    Inputs:
        itc_rate, capacity_mw, energy_price, annual_cycles, capex_usd_kwh,
        discount_rate, lifetime_years
    """
    itc = params.get("itc_rate", 0.30)
    mw = params.get("capacity_mw", 10.0)
    price = params.get("energy_price", 50.0)
    cycles = params.get("annual_cycles", 250.0)
    capex_kwh = params.get("capex_usd_kwh", 300.0)
    dr = params.get("discount_rate", 0.08)
    years = int(params.get("lifetime_years", 15))

    capex = capex_kwh * mw * 1000 * 4  # 4h duration
    capex_net = capex * (1 - itc)

    annual_revenue = mw * price * cycles * 4  # 4h dispatch per cycle
    annual_opex = capex * 0.01
    annual_cf = annual_revenue - annual_opex

    npv = -capex_net + sum(annual_cf / (1 + dr) ** y for y in range(1, years + 1))
    irr_est = annual_cf / max(capex_net, 1.0)   # Simplified

    return {
        "revenue_usd": annual_revenue,
        "fleet_mw": mw,
        "customer_savings_usd": annual_revenue * 0.3,
        "carbon_tons": mw * cycles * 0.4,
        "npv_usd": npv,
        "irr": irr_est,
    }
