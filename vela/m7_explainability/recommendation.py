"""Actionable recommendations from optimizer output."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple


class Recommendation(NamedTuple):
    category: str           # "dispatch", "configuration", "market", "risk"
    priority: str           # "high", "medium", "low"
    title: str
    description: str
    estimated_value: float  # $/day or $/year
    action_items: list[str]


@dataclass
class RecommendationEngine:
    """
    Generates actionable recommendations from VPP optimization results.

    Analyzes:
    - Revenue performance vs. benchmark
    - Binding constraints (where capacity upgrades add value)
    - Market participation opportunities
    - SOC management patterns
    - Price spike exposure
    """
    capacity_mwh: float = 10.0
    power_mw: float = 5.0

    def analyze(
        self,
        charge_mw: list[float],
        discharge_mw: list[float],
        soc: list[float],
        lmp: list[float],
        reg_up_mw: list[float] | None = None,
        reg_up_price: list[float] | None = None,
        reg_down_mw: list[float] | None = None,
    ) -> list[Recommendation]:
        """Generate recommendations from a 24-hour dispatch plan."""
        recs = []
        T = len(lmp)
        ch = np.array(charge_mw)
        dis = np.array(discharge_mw)
        soc_arr = np.array(soc)
        lmp_arr = np.array(lmp)
        median_lmp = float(np.median(lmp_arr))
        mean_lmp = float(np.mean(lmp_arr))

        # 1. Check for missed arbitrage opportunities
        idle_high_price = np.where((lmp_arr > median_lmp * 1.3) & (dis < 0.1) & (soc_arr > 0.2))[0]
        if len(idle_high_price) > 0:
            avg_missed_price = float(np.mean(lmp_arr[idle_high_price]))
            recs.append(Recommendation(
                category="dispatch",
                priority="high",
                title="Missed discharge opportunities during high-price periods",
                description=(
                    f"{len(idle_high_price)} intervals had LMP > ${avg_missed_price:.1f}/MWh "
                    f"(1.3x median) but asset was idle with available SOC."
                ),
                estimated_value=len(idle_high_price) * self.power_mw * avg_missed_price * 0.1,
                action_items=[
                    f"Lower discharge threshold from current level to ${median_lmp * 1.15:.1f}/MWh",
                    "Review SOC targets to ensure headroom for discharge during high prices",
                ],
            ))

        # 2. Check for missed charging windows
        idle_low_price = np.where((lmp_arr < median_lmp * 0.7) & (ch < 0.1) & (soc_arr < 0.8))[0]
        if len(idle_low_price) > 2:
            avg_missed_price = float(np.mean(lmp_arr[idle_low_price]))
            recs.append(Recommendation(
                category="dispatch",
                priority="medium",
                title="Missed low-cost charging opportunities",
                description=(
                    f"{len(idle_low_price)} intervals had LMP < ${avg_missed_price:.1f}/MWh "
                    f"with available charge capacity."
                ),
                estimated_value=len(idle_low_price) * self.power_mw * (median_lmp - avg_missed_price) * 0.05,
                action_items=[
                    f"Raise charge threshold to ${median_lmp * 0.8:.1f}/MWh",
                    "Enable overnight scheduled charging during consistently low-price hours",
                ],
            ))

        # 3. Power binding analysis
        power_bound_discharge = np.where(dis > self.power_mw * 0.95)[0]
        if len(power_bound_discharge) > 0:
            avg_binding_lmp = float(np.mean(lmp_arr[power_bound_discharge]))
            incr_revenue = len(power_bound_discharge) * 1.0 * avg_binding_lmp  # $/MW-day
            recs.append(Recommendation(
                category="configuration",
                priority="high" if incr_revenue > 500 else "medium",
                title="Power capacity is binding during high-price hours",
                description=(
                    f"Asset hit max power ({self.power_mw} MW) in "
                    f"{len(power_bound_discharge)} intervals at avg ${avg_binding_lmp:.1f}/MWh. "
                    f"Estimated value of +1 MW: ${incr_revenue:.0f}/day."
                ),
                estimated_value=incr_revenue * 365,
                action_items=[
                    f"Evaluate cost of upgrading inverter capacity by 1-2 MW",
                    f"At ${incr_revenue*365:,.0f}/year, additional capacity likely economical",
                ],
            ))

        # 4. Ancillary services recommendation
        if reg_up_mw is None or all(v < 0.1 for v in reg_up_mw):
            as_opportunity = mean_lmp * 0.25  # Typical reg price is ~25% of LMP
            recs.append(Recommendation(
                category="market",
                priority="medium",
                title="Not participating in regulation market",
                description=(
                    f"Asset is not bidding into regulation market. "
                    f"Estimated avg reg-up price: ${as_opportunity:.1f}/MWh."
                ),
                estimated_value=self.power_mw * 0.3 * as_opportunity * 24 * 365,
                action_items=[
                    "Register asset for ERCOT Responsive Reserve or CAISO Regulation",
                    "Ensure asset has sufficient SOC buffer (20-80%) for regulation compliance",
                    "Enable co-optimization of energy + ancillary services",
                ],
            ))

        # 5. Extreme SOC events
        low_soc_events = np.where(soc_arr < 0.12)[0]
        high_soc_events = np.where(soc_arr > 0.92)[0]
        if len(low_soc_events) > 0:
            recs.append(Recommendation(
                category="risk",
                priority="medium",
                title="SOC approaching minimum in some intervals",
                description=(
                    f"SOC dropped near minimum ({min(soc_arr[low_soc_events]):.1%}) "
                    f"in {len(low_soc_events)} intervals, limiting discharge capability."
                ),
                estimated_value=0.0,
                action_items=[
                    "Increase soc_min threshold from current value",
                    "Enable predictive SOC management using day-ahead forecast",
                ],
            ))

        return sorted(recs, key=lambda r: {"high": 0, "medium": 1, "low": 2}[r.priority])
