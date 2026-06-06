"""
Retail electricity tariff modeling for VPP customer bill analysis.

Models TOU, demand charge, RTP, and tiered rate structures to quantify
VPP value-to-customer through demand reduction and load shifting.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
import numpy as np


class TariffType(str, Enum):
    FLAT = "flat"
    TOU = "tou"             # Time-of-Use
    DEMAND = "demand"       # Demand charge ($/kW-month)
    TIERED = "tiered"
    RTP = "rtp"             # Real-Time Pricing


@dataclass
class TariffBlock:
    """Represents one block in a tiered or TOU tariff."""
    name: str
    hours: List[int]        # Hours of day this block applies (0-23)
    days: List[int]         # Days of week (0=Mon, 6=Sun)
    energy_rate_usd_kwh: float
    demand_rate_usd_kw_month: float = 0.0


@dataclass
class TariffStructure:
    tariff_id: str
    name: str
    tariff_type: TariffType
    blocks: List[TariffBlock]
    customer_charge_usd_month: float = 10.0
    demand_measurement_window_min: int = 15


class BillCalculator:
    """
    Calculates monthly electricity bills and VPP savings potential.
    """

    def compute_bill(
        self,
        tariff: TariffStructure,
        hourly_load_kw: List[float],    # 8760 values (1 year)
        month: int,                      # 1-12
    ) -> Dict[str, float]:
        """
        Compute monthly electricity bill breakdown.

        Returns:
            energy_charge, demand_charge, customer_charge, total
        """
        # Select hours for this month (approximate: 730 hours)
        start_h = (month - 1) * 730
        end_h = min(start_h + 730, len(hourly_load_kw))
        monthly_load = hourly_load_kw[start_h:end_h]

        energy_cost = 0.0
        peak_demand_kw = 0.0

        for h_rel, load in enumerate(monthly_load):
            h_abs = start_h + h_rel
            hour_of_day = h_abs % 24
            day_of_week = (h_abs // 24) % 7

            # Find applicable tariff block
            rate = tariff.blocks[0].energy_rate_usd_kwh  # Default
            demand_rate = tariff.blocks[0].demand_rate_usd_kw_month
            for block in tariff.blocks:
                if hour_of_day in block.hours and day_of_week in block.days:
                    rate = block.energy_rate_usd_kwh
                    demand_rate = block.demand_rate_usd_kw_month
                    break

            energy_cost += load * rate   # kWh at $/kWh
            peak_demand_kw = max(peak_demand_kw, load)

        demand_cost = peak_demand_kw * demand_rate if demand_rate > 0 else 0.0

        return {
            "energy_charge_usd": energy_cost,
            "demand_charge_usd": demand_cost,
            "customer_charge_usd": tariff.customer_charge_usd_month,
            "total_usd": energy_cost + demand_cost + tariff.customer_charge_usd_month,
        }

    def bill_savings(
        self,
        tariff: TariffStructure,
        baseline_load_kw: List[float],
        modified_load_kw: List[float],
        month: int,
    ) -> float:
        """Compute monthly savings from VPP-enabled load modification."""
        baseline = self.compute_bill(tariff, baseline_load_kw, month)
        modified = self.compute_bill(tariff, modified_load_kw, month)
        return baseline["total_usd"] - modified["total_usd"]
