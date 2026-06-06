"""
Utility tariff tracker for VPP customer rate management.

Tracks retail tariff changes across utility service territories,
models impact on VPP customer bill savings, and maintains tariff history.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class TariffRevision:
    revision_id: str
    utility: str
    effective_date: str
    energy_rate_usd_kwh: float
    demand_rate_usd_kw: float
    customer_charge_usd_month: float
    tou_peak_multiplier: float = 1.0
    notes: str = ""


@dataclass
class TariffImpactAnalysis:
    utility: str
    current_bill_usd: float
    new_bill_usd: float
    delta_usd: float
    delta_pct: float
    vpp_savings_delta_usd: float   # How VPP savings change under new tariff


class TariffTracker:
    """
    Maintains historical tariff database and analyzes revision impacts.
    """

    def __init__(self) -> None:
        self._tariffs: Dict[str, List[TariffRevision]] = {}

    def add_revision(self, revision: TariffRevision) -> None:
        self._tariffs.setdefault(revision.utility, []).append(revision)
        self._tariffs[revision.utility].sort(key=lambda r: r.effective_date)

    def current_tariff(self, utility: str, date: str = "9999-12-31") -> Optional[TariffRevision]:
        """Return the most recent tariff in effect before the given date."""
        revisions = [r for r in self._tariffs.get(utility, []) if r.effective_date <= date]
        return revisions[-1] if revisions else None

    def tariff_history(self, utility: str) -> List[TariffRevision]:
        return self._tariffs.get(utility, [])

    def analyze_impact(
        self,
        utility: str,
        annual_load_kwh: float,
        peak_demand_kw: float,
        old_date: str,
        new_date: str,
        vpp_savings_old_usd: float,
    ) -> Optional[TariffImpactAnalysis]:
        old = self.current_tariff(utility, old_date)
        new = self.current_tariff(utility, new_date)
        if not old or not new:
            return None

        def annual_bill(t: TariffRevision) -> float:
            energy = annual_load_kwh * t.energy_rate_usd_kwh
            demand = peak_demand_kw * t.demand_rate_usd_kw * 12
            customer = t.customer_charge_usd_month * 12
            return energy + demand + customer

        old_bill = annual_bill(old)
        new_bill = annual_bill(new)
        delta = new_bill - old_bill

        # VPP savings as % of bill remain approximately constant if tariff increases
        savings_ratio = vpp_savings_old_usd / max(old_bill, 1.0)
        new_vpp_savings = savings_ratio * new_bill
        delta_savings = new_vpp_savings - vpp_savings_old_usd

        return TariffImpactAnalysis(
            utility=utility,
            current_bill_usd=old_bill,
            new_bill_usd=new_bill,
            delta_usd=delta,
            delta_pct=delta / max(old_bill, 1.0) * 100,
            vpp_savings_delta_usd=delta_savings,
        )
