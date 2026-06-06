"""
Customer bill calculation with VPP savings attribution.

Computes baseline vs VPP-modified electricity bills, attributes
savings to specific VPP services (arbitrage, DR, self-consumption).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class CustomerBill:
    customer_id: str
    period: str
    baseline_energy_usd: float
    baseline_demand_usd: float
    baseline_total_usd: float
    vpp_energy_usd: float
    vpp_demand_usd: float
    vpp_total_usd: float
    savings_usd: float
    savings_pct: float
    arbitrage_savings_usd: float
    dr_savings_usd: float
    self_consumption_savings_usd: float


class CustomerBillCalculator:
    """Calculates VPP bill savings for individual customers."""

    def compute(
        self,
        customer_id: str,
        period: str,
        baseline_load_kw: List[float],     # Hourly baseline load
        vpp_load_kw: List[float],          # VPP-modified load
        energy_rate_usd_kwh: float = 0.12,
        demand_rate_usd_kw: float = 15.0,
        peak_hours: Optional[List[int]] = None,   # Hours that face TOU peak rate
        tou_multiplier: float = 1.5,
    ) -> CustomerBill:
        """Compute bill with demand charge and TOU energy pricing."""
        if peak_hours is None:
            peak_hours = list(range(14, 20))   # 2pm–8pm default

        def calc_bill(load_kw: List[float]) -> Dict[str, float]:
            energy = 0.0
            for h, kw in enumerate(load_kw):
                rate = energy_rate_usd_kwh * (tou_multiplier if h % 24 in peak_hours else 1.0)
                energy += kw * rate  # kWh * $/kWh
            peak = max((kw for h, kw in enumerate(load_kw) if h % 24 in peak_hours), default=0.0)
            demand = peak * demand_rate_usd_kw
            return {"energy": energy, "demand": demand, "total": energy + demand}

        baseline = calc_bill(baseline_load_kw)
        vpp = calc_bill(vpp_load_kw)
        savings = baseline["total"] - vpp["total"]

        # Attribution: decompose savings
        # Arbitrage = energy charge reduction in off-peak hours
        arb_savings = max(0.0, baseline["energy"] - vpp["energy"]) * 0.5
        dr_savings = max(0.0, baseline["demand"] - vpp["demand"])
        self_cons = max(0.0, savings - arb_savings - dr_savings)

        return CustomerBill(
            customer_id=customer_id,
            period=period,
            baseline_energy_usd=baseline["energy"],
            baseline_demand_usd=baseline["demand"],
            baseline_total_usd=baseline["total"],
            vpp_energy_usd=vpp["energy"],
            vpp_demand_usd=vpp["demand"],
            vpp_total_usd=vpp["total"],
            savings_usd=savings,
            savings_pct=savings / max(baseline["total"], 1.0) * 100,
            arbitrage_savings_usd=arb_savings,
            dr_savings_usd=dr_savings,
            self_consumption_savings_usd=self_cons,
        )
