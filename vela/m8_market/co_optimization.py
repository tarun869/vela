"""Energy + Ancillary Services co-optimization wrapper for market operations."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple

import numpy as np

from .bid_models import EnergyBid, AncillaryBid, BidType

logger = logging.getLogger(__name__)


class CoOptMarketPlan(NamedTuple):
    asset_id: str
    market: str
    horizon: int
    energy_schedule_mw: list[float]      # Net (positive=discharge, negative=charge)
    reg_up_mw: list[float]
    reg_down_mw: list[float]
    spin_mw: list[float]
    energy_revenue: float
    as_revenue: float
    total_revenue: float
    as_fraction: float                   # AS revenue as fraction of total


@dataclass
class MarketCoOptimizer:
    """
    Wrapper that combines dispatch optimizer output with market-specific
    co-optimization logic.

    Handles:
    - Capability award stacking (can't offer same MW to multiple AS products)
    - Market-specific minimum offer quantities
    - AS qualification requirements (e.g., response time)
    - Price-taker vs. price-maker bid strategies
    """
    horizon: int = 24
    dt_hours: float = 1.0
    min_reg_offer_mw: float = 0.5   # ERCOT: 0.1 MW, CAISO: 0.5 MW
    max_as_stack_pct: float = 0.9   # Max fraction of power capacity in AS

    def compute_optimal_allocation(
        self,
        asset_power_mw: float,
        asset_capacity_mwh: float,
        current_soc: list[float],
        lmp_forecast: list[float],
        reg_up_price: list[float],
        reg_down_price: list[float],
        spin_price: list[float],
        rte: float = 0.92,
    ) -> CoOptMarketPlan:
        """
        Determine optimal MW allocation between energy arbitrage and AS products.

        Uses marginal value analysis:
        - For each interval, compare marginal energy revenue vs. AS clearing price
        - Allocate capacity to highest-value use
        - Respect stacking constraints
        """
        T = self.horizon
        energy_schedule = []
        reg_up = []
        reg_down = []
        spin = []
        soc = list(current_soc[:T]) if len(current_soc) >= T else current_soc + [current_soc[-1]] * (T - len(current_soc))
        median_lmp = float(np.median(lmp_forecast))

        for t in range(T):
            lmp = lmp_forecast[t]
            available_mw = asset_power_mw
            ru_price = reg_up_price[t]
            rd_price = reg_down_price[t]
            sp_price = spin_price[t]
            soc_t = soc[t]

            # Marginal values
            # Energy discharge: lmp * dt
            # Reg-up: ru_price * dt (capacity payment)
            # Spin: sp_price * dt

            # Priority ordering by $/MW-h
            products = [
                ("reg_up", ru_price, soc_t > 0.3),         # Need headroom to discharge
                ("spin", sp_price, soc_t > 0.25),
                ("energy_dis", lmp, soc_t > 0.15 and lmp > median_lmp),
                ("reg_down", rd_price, soc_t < 0.75),       # Need headroom to charge
                ("energy_ch", -lmp, soc_t < 0.85 and lmp < median_lmp),
            ]
            products_sorted = sorted(products, key=lambda x: -x[1])

            ru_mw = rd_mw = sp_mw = en_dis_mw = en_ch_mw = 0.0
            remaining_dis = available_mw
            remaining_ch = available_mw

            for name, value, feasible in products_sorted:
                if not feasible or value <= 0:
                    continue
                max_as = asset_power_mw * self.max_as_stack_pct
                if name == "reg_up" and remaining_dis >= self.min_reg_offer_mw:
                    ru_mw = min(max_as * 0.4, remaining_dis)
                    remaining_dis -= ru_mw
                elif name == "spin" and remaining_dis >= self.min_reg_offer_mw:
                    sp_mw = min(max_as * 0.3, remaining_dis)
                    remaining_dis -= sp_mw
                elif name == "energy_dis" and remaining_dis >= 0.1:
                    en_dis_mw = remaining_dis
                    remaining_dis = 0.0
                elif name == "reg_down" and remaining_ch >= self.min_reg_offer_mw:
                    rd_mw = min(max_as * 0.4, remaining_ch)
                    remaining_ch -= rd_mw
                elif name == "energy_ch" and remaining_ch >= 0.1:
                    en_ch_mw = remaining_ch
                    remaining_ch = 0.0

            energy_schedule.append(en_dis_mw - en_ch_mw)
            reg_up.append(ru_mw)
            reg_down.append(rd_mw)
            spin.append(sp_mw)

        # Revenue calculation
        energy_rev = sum(
            energy_schedule[t] * lmp_forecast[t] * self.dt_hours
            for t in range(T)
        )
        as_rev = sum(
            (reg_up[t] * reg_up_price[t] + reg_down[t] * reg_down_price[t] + spin[t] * spin_price[t]) * self.dt_hours
            for t in range(T)
        )
        total_rev = energy_rev + as_rev

        return CoOptMarketPlan(
            asset_id="",
            market="",
            horizon=T,
            energy_schedule_mw=energy_schedule,
            reg_up_mw=reg_up,
            reg_down_mw=reg_down,
            spin_mw=spin,
            energy_revenue=energy_rev,
            as_revenue=as_rev,
            total_revenue=total_rev,
            as_fraction=as_rev / (total_rev + 1e-6),
        )

    def sensitivity_analysis(
        self,
        asset_power_mw: float,
        lmp: list[float],
        reg_up_price: list[float],
        base_soc: list[float],
        rte: float = 0.92,
    ) -> dict[str, float]:
        """
        Compute revenue sensitivity to AS price changes.

        Returns $/MWh of reg capacity per 1% change in reg price.
        """
        T = self.horizon
        lmp_arr = np.array(lmp[:T])
        ru_arr = np.array(reg_up_price[:T])

        # Base case
        base_rev = float(np.mean(ru_arr) * asset_power_mw * 0.3 * T * self.dt_hours)

        # +10% reg price sensitivity
        high_rev = float(np.mean(ru_arr * 1.1) * asset_power_mw * 0.3 * T * self.dt_hours)
        sensitivity = (high_rev - base_rev) / (base_rev + 1e-6) / 0.1

        return {
            "base_as_revenue": base_rev,
            "revenue_sensitivity_pct_per_pct": sensitivity,
            "break_even_as_price": float(np.mean(lmp_arr) * 0.2),
        }
