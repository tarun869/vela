"""
Regulatory incentive and rebate tracker for VPP asset economics.

Tracks federal ITC/PTC tax credits, state rebates, utility incentives,
and carbon market incentives to compute accurate project economics.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class IncentiveType(str, Enum):
    ITC = "itc"               # Investment Tax Credit
    PTC = "ptc"               # Production Tax Credit
    CEIP = "ceip"             # Clean Energy Investment Program
    STATE_REBATE = "state_rebate"
    UTILITY_REBATE = "utility_rebate"
    SGIP = "sgip"             # CA Self Generation Incentive Program
    PACE = "pace"             # Property Assessed Clean Energy
    MACRS = "macrs"           # Modified Accelerated Cost Recovery


@dataclass
class Incentive:
    incentive_id: str
    name: str
    incentive_type: IncentiveType
    jurisdiction: str          # Federal, state name, or utility name
    technology: List[str]      # Eligible technologies
    value_pct: float = 0.0    # % of project cost
    value_usd_kwh: float = 0.0  # $/kWh installed (for rebates)
    value_usd_kw: float = 0.0   # $/kW installed (for capacity rebates)
    max_usd: Optional[float] = None   # Cap on incentive
    expiry_date: Optional[str] = None
    stackable: bool = True     # Can combine with other incentives


# 2024-2025 key incentives (simplified)
KNOWN_INCENTIVES: List[Incentive] = [
    Incentive("IRA-ITC-30", "IRA Storage ITC", IncentiveType.ITC, "Federal",
              ["battery_storage", "solar+storage"], value_pct=0.30, expiry_date="2032-12-31"),
    Incentive("IRA-ITC-BONUS-10", "IRA Energy Community Bonus ITC", IncentiveType.ITC, "Federal",
              ["battery_storage", "solar", "wind"], value_pct=0.10, expiry_date="2032-12-31"),
    Incentive("CA-SGIP-2024", "California SGIP", IncentiveType.SGIP, "California",
              ["battery_storage"], value_usd_kwh=0.20, max_usd=1_000_000),
    Incentive("TX-EPCR-2024", "Texas EPCR", IncentiveType.STATE_REBATE, "Texas",
              ["battery_storage", "solar+storage"], value_usd_kw=50.0, max_usd=500_000),
]


class IncentiveTracker:
    """
    Computes applicable incentives and net project cost for VPP assets.
    """

    def __init__(self, custom_incentives: Optional[List[Incentive]] = None) -> None:
        self._incentives = list(KNOWN_INCENTIVES) + (custom_incentives or [])

    def eligible_incentives(
        self,
        technology: str,
        jurisdiction: str,
        date: str = "2025-01-01",
    ) -> List[Incentive]:
        """Return incentives eligible for a technology in a given jurisdiction."""
        eligible: List[Incentive] = []
        for inc in self._incentives:
            if technology not in inc.technology:
                continue
            if inc.jurisdiction not in ("Federal", jurisdiction):
                continue
            if inc.expiry_date and inc.expiry_date < date:
                continue
            eligible.append(inc)
        return eligible

    def compute_incentive_value(
        self,
        incentive: Incentive,
        project_cost_usd: float,
        capacity_kw: float,
        capacity_kwh: float,
    ) -> float:
        """Compute dollar value of a specific incentive."""
        if incentive.value_pct > 0:
            value = incentive.value_pct * project_cost_usd
        elif incentive.value_usd_kwh > 0:
            value = incentive.value_usd_kwh * capacity_kwh
        elif incentive.value_usd_kw > 0:
            value = incentive.value_usd_kw * capacity_kw
        else:
            value = 0.0

        if incentive.max_usd is not None:
            value = min(value, incentive.max_usd)
        return value

    def total_incentive_value(
        self,
        technology: str,
        jurisdiction: str,
        project_cost_usd: float,
        capacity_kw: float,
        capacity_kwh: float,
        date: str = "2025-01-01",
    ) -> Dict[str, float]:
        """Sum all applicable incentives."""
        eligible = self.eligible_incentives(technology, jurisdiction, date)
        breakdown: Dict[str, float] = {}
        for inc in eligible:
            v = self.compute_incentive_value(inc, project_cost_usd, capacity_kw, capacity_kwh)
            breakdown[inc.name] = v
        return breakdown
