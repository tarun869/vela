"""
Stress testing framework for VPP operational and financial resilience.

Applies extreme adverse scenarios (price collapse, extended outages,
extreme weather, cyber attack) to test VPP system robustness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
import numpy as np


@dataclass
class StressScenario:
    scenario_id: str
    name: str
    category: str    # "market", "weather", "cyber", "operational", "regulatory"
    parameter_shocks: Dict[str, float]   # Multiplicative shocks (1.0 = no change)
    duration_days: int
    probability: float = 0.01   # Annual probability
    description: str = ""


@dataclass
class StressTestResult:
    scenario_id: str
    revenue_impact_usd: float
    revenue_pct_change: float
    max_drawdown_usd: float
    days_negative_cashflow: int
    recovery_days: int
    survived: bool    # Can VPP remain solvent and operational?


# Pre-defined stress scenarios for energy storage VPPs
DEFAULT_SCENARIOS = [
    StressScenario("ST-PRICE-COLLAPSE", "Energy price collapse",
                   "market", {"energy_price": 0.20, "ancillary_price": 0.30},
                   90, 0.05, "LMP drops to $8/MWh average for 90 days"),
    StressScenario("ST-EXTENDED-OUTAGE", "Extended fleet outage",
                   "operational", {"availability": 0.30},
                   30, 0.02, "30% fleet availability due to degradation failure"),
    StressScenario("ST-CYBER-ATTACK", "Cyber disruption",
                   "cyber", {"availability": 0.50, "dispatch_delay_h": 4.0},
                   7, 0.01, "Partial control system compromise"),
    StressScenario("ST-EXTREME-HEAT", "Extreme heat wave",
                   "weather", {"derating": 0.85, "demand_surge": 1.40},
                   14, 0.10, "Heat wave increases load 40%, derates batteries 15%"),
    StressScenario("ST-POLICY-REVERSAL", "ITC elimination",
                   "regulatory", {"itc_rate": 0.0, "capex_factor": 1.0},
                   365, 0.03, "ITC eliminated, no retroactive relief"),
]


class StressTester:
    """
    Applies stress scenarios to VPP financial and operational model.
    """

    def __init__(
        self,
        vpp_model: Callable[[Dict[str, float]], Dict[str, float]],
        baseline_params: Dict[str, float],
        cash_reserve_usd: float = 2_000_000.0,
    ) -> None:
        self.model = vpp_model
        self.baseline = baseline_params
        self.cash = cash_reserve_usd

    def run_scenario(self, scenario: StressScenario) -> StressTestResult:
        """Apply stress shocks and compute financial impact."""
        stressed_params = {}
        for k, v in self.baseline.items():
            shock = scenario.parameter_shocks.get(k, 1.0)
            stressed_params[k] = v * shock

        baseline_out = self.model(self.baseline)
        stressed_out = self.model(stressed_params)

        baseline_annual = baseline_out.get("revenue_usd", 1.0)
        stressed_annual = stressed_out.get("revenue_usd", 0.0)

        impact = (stressed_annual - baseline_annual) * (scenario.duration_days / 365)
        pct = (stressed_annual - baseline_annual) / max(abs(baseline_annual), 1.0) * 100

        # Daily cashflow during stress
        daily_cf = (stressed_annual - baseline_out.get("opex_usd", 0.0)) / 365
        daily_baseline_cf = (baseline_annual - baseline_out.get("opex_usd", 0.0)) / 365

        days_negative = max(0, int(-daily_cf * 30)) if daily_cf < 0 else 0
        drawdown = max(0.0, -impact)
        survived = (self.cash + impact) > 0

        # Recovery: time to earn back the drawdown at normal rates
        recovery = int(drawdown / max(daily_baseline_cf, 1.0)) if daily_baseline_cf > 0 else 999

        return StressTestResult(
            scenario_id=scenario.scenario_id,
            revenue_impact_usd=impact,
            revenue_pct_change=pct,
            max_drawdown_usd=drawdown,
            days_negative_cashflow=days_negative,
            recovery_days=recovery,
            survived=survived,
        )

    def run_all(self, scenarios: Optional[List[StressScenario]] = None) -> List[StressTestResult]:
        """Run all stress scenarios."""
        target = scenarios or DEFAULT_SCENARIOS
        return [self.run_scenario(s) for s in target]

    def worst_case(self, results: List[StressTestResult]) -> Optional[StressTestResult]:
        """Return the most severe result by revenue impact."""
        if not results:
            return None
        return min(results, key=lambda r: r.revenue_impact_usd)
