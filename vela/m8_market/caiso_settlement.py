"""CAISO market settlement calculation (market-facing, not final settlement)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class CAISOSettlementInterval(NamedTuple):
    interval_start: datetime
    da_schedule_mwh: float     # Day-ahead scheduled energy
    rt_dispatch_mwh: float     # Real-time dispatched energy
    da_lmp: float              # Day-ahead LMP
    rt_lmp: float              # Real-time LMP
    da_energy_revenue: float   # DA schedule * DA LMP
    rt_deviation_revenue: float  # (RT - DA) * RT LMP
    total_interval_revenue: float


@dataclass
class CAISOSettlementCalculator:
    """
    CAISO settlement calculation for storage resources.

    CAISO two-settlement system:
    1. Day-Ahead (DA): settled at DA LMP for scheduled quantity
    2. Real-Time (RT): deviation from DA settled at RT LMP (5-min or hourly)

    Total revenue per interval:
        = DA_schedule * DA_LMP + (RT_dispatch - DA_schedule) * RT_LMP

    For storage, charging is negative energy (load), discharging is positive.
    """
    resource_id: str
    market: str = "CAISO"

    def calculate(
        self,
        da_schedule: list[float],    # MW per interval (positive=discharge)
        rt_dispatch: list[float],    # MW per interval (actual)
        da_lmp: list[float],         # $/MWh
        rt_lmp: list[float],         # $/MWh
        start_time: datetime,
        dt_hours: float = 1.0,
    ) -> list[CAISOSettlementInterval]:
        """
        Compute per-interval settlement.

        Returns list of CAISOSettlementInterval for each time step.
        """
        T = min(len(da_schedule), len(rt_dispatch), len(da_lmp), len(rt_lmp))
        intervals = []

        for t in range(T):
            ts = start_time + timedelta(hours=t * dt_hours)
            da_mwh = da_schedule[t] * dt_hours
            rt_mwh = rt_dispatch[t] * dt_hours

            da_rev = da_mwh * da_lmp[t]
            rt_dev_rev = (rt_mwh - da_mwh) * rt_lmp[t]
            total_rev = da_rev + rt_dev_rev

            intervals.append(CAISOSettlementInterval(
                interval_start=ts,
                da_schedule_mwh=da_mwh,
                rt_dispatch_mwh=rt_mwh,
                da_lmp=da_lmp[t],
                rt_lmp=rt_lmp[t],
                da_energy_revenue=da_rev,
                rt_deviation_revenue=rt_dev_rev,
                total_interval_revenue=total_rev,
            ))

        return intervals

    def summary(self, intervals: list[CAISOSettlementInterval]) -> dict[str, float]:
        """Aggregate settlement results."""
        if not intervals:
            return {}
        da_rev = sum(i.da_energy_revenue for i in intervals)
        rt_dev_rev = sum(i.rt_deviation_revenue for i in intervals)
        total = da_rev + rt_dev_rev
        da_mwh = sum(i.da_schedule_mwh for i in intervals)
        rt_mwh = sum(i.rt_dispatch_mwh for i in intervals)

        return {
            "da_energy_revenue": da_rev,
            "rt_deviation_revenue": rt_dev_rev,
            "total_revenue": total,
            "da_schedule_mwh": da_mwh,
            "rt_dispatch_mwh": rt_mwh,
            "avg_da_lmp": float(np.mean([i.da_lmp for i in intervals])),
            "avg_rt_lmp": float(np.mean([i.rt_lmp for i in intervals])),
            "n_intervals": float(len(intervals)),
        }

    def regulation_settlement(
        self,
        reg_up_awarded_mw: list[float],
        reg_down_awarded_mw: list[float],
        reg_up_mileage: list[float],    # Actual regulation mileage (MW deployed)
        reg_down_mileage: list[float],
        ru_cap_price: list[float],      # $/MW-h capacity payment
        rd_cap_price: list[float],
        ru_perf_price: list[float],     # $/MWh performance payment
        rd_perf_price: list[float],
        dt_hours: float = 1.0,
    ) -> dict[str, float]:
        """
        CAISO regulation settlement with capacity + performance payments.

        CAISO pays:
        1. Capacity payment: awarded_mw * cap_price * dt
        2. Performance payment: mileage * perf_price * dt
        """
        T = len(reg_up_awarded_mw)
        ru_cap_rev = sum(reg_up_awarded_mw[t] * ru_cap_price[t] * dt_hours for t in range(T))
        rd_cap_rev = sum(reg_down_awarded_mw[t] * rd_cap_price[t] * dt_hours for t in range(T))
        ru_perf_rev = sum(reg_up_mileage[t] * ru_perf_price[t] * dt_hours for t in range(T))
        rd_perf_rev = sum(reg_down_mileage[t] * rd_perf_price[t] * dt_hours for t in range(T))

        return {
            "reg_up_capacity_revenue": ru_cap_rev,
            "reg_down_capacity_revenue": rd_cap_rev,
            "reg_up_performance_revenue": ru_perf_rev,
            "reg_down_performance_revenue": rd_perf_rev,
            "total_regulation_revenue": ru_cap_rev + rd_cap_rev + ru_perf_rev + rd_perf_rev,
        }
