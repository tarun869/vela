"""CAISO-specific settlement calculation including HASP, IFM, and RTM."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class CAISOInterval(NamedTuple):
    interval_start: datetime
    da_schedule_mwh: float
    hasp_adjustment_mwh: float   # Hour-Ahead Scheduling Procedure adjustment
    rt_dispatch_mwh: float       # 5-minute actual dispatch
    ifm_lmp: float               # Integrated Forward Market LMP (DA)
    hasp_lmp: float              # Hour-Ahead LMP
    rtpd_lmp: float              # Real-Time Pre-Dispatch LMP
    rted_lmp: float              # Real-Time Economic Dispatch LMP (5-min)
    ifm_revenue: float
    hasp_revenue: float
    rtd_revenue: float
    total_revenue: float


@dataclass
class CAISOSettlementCalculator:
    """
    CAISO settlement engine for storage resources.

    CAISO has a complex multi-settlement system:
    1. IFM (Integrated Forward Market / Day-Ahead):
       - Clears at 10 AM for next operating day
       - Energy, AS, and residual unit commitment
    2. HASP (Hour-Ahead Scheduling Procedure):
       - Runs at T-75 minutes before operating hour
       - Adjusts schedules for forecast updates
    3. RTD (Real-Time Dispatch):
       - 5-minute economic dispatch
       - RTED (Real-Time Economic Dispatch): 5-min intervals
       - RTPD (Real-Time Pre-Dispatch): 15-min advisory

    Settlement:
    - IFM: DA schedule * IFM LMP
    - HASP: (HASP schedule - DA schedule) * HASP LMP
    - RTD: (actual dispatch - HASP schedule) * RTPD/RTED LMP
    """
    resource_id: str
    pnode: str = ""  # Pricing node

    def calculate_full_settlement(
        self,
        da_schedule: list[float],
        hasp_schedule: list[float],
        rt_dispatch: list[float],
        ifm_lmp: list[float],
        hasp_lmp: list[float],
        rtpd_lmp: list[float],
        rted_lmp: list[float],
        start_time: datetime,
        dt_hours: float = 1.0,
    ) -> list[CAISOInterval]:
        """
        Compute full CAISO three-settlement revenue.
        """
        T = min(
            len(da_schedule), len(hasp_schedule), len(rt_dispatch),
            len(ifm_lmp), len(hasp_lmp), len(rtpd_lmp), len(rted_lmp)
        )
        intervals = []

        for t in range(T):
            ts = start_time + timedelta(hours=t * dt_hours)
            da_mwh = da_schedule[t] * dt_hours
            hasp_mwh = hasp_schedule[t] * dt_hours
            rt_mwh = rt_dispatch[t] * dt_hours

            # Settlement calculation per layer
            ifm_rev = da_mwh * ifm_lmp[t]
            hasp_rev = (hasp_mwh - da_mwh) * hasp_lmp[t]
            rtd_rev = (rt_mwh - hasp_mwh) * rted_lmp[t]
            total = ifm_rev + hasp_rev + rtd_rev

            intervals.append(CAISOInterval(
                interval_start=ts,
                da_schedule_mwh=da_mwh,
                hasp_adjustment_mwh=hasp_mwh - da_mwh,
                rt_dispatch_mwh=rt_mwh,
                ifm_lmp=ifm_lmp[t],
                hasp_lmp=hasp_lmp[t],
                rtpd_lmp=rtpd_lmp[t],
                rted_lmp=rted_lmp[t],
                ifm_revenue=ifm_rev,
                hasp_revenue=hasp_rev,
                rtd_revenue=rtd_rev,
                total_revenue=total,
            ))

        return intervals

    def summary(self, intervals: list[CAISOInterval]) -> dict[str, float]:
        """Aggregate CAISO settlement summary."""
        if not intervals:
            return {}
        return {
            "ifm_revenue": sum(i.ifm_revenue for i in intervals),
            "hasp_revenue": sum(i.hasp_revenue for i in intervals),
            "rtd_revenue": sum(i.rtd_revenue for i in intervals),
            "total_revenue": sum(i.total_revenue for i in intervals),
            "total_da_mwh": sum(i.da_schedule_mwh for i in intervals),
            "total_rt_mwh": sum(i.rt_dispatch_mwh for i in intervals),
            "avg_ifm_lmp": float(np.mean([i.ifm_lmp for i in intervals])),
            "avg_rted_lmp": float(np.mean([i.rted_lmp for i in intervals])),
            "da_rt_lmp_spread": float(np.mean([i.ifm_lmp - i.rted_lmp for i in intervals])),
        }

    def as_settlement(
        self,
        product: str,
        awarded_mw: list[float],
        clearing_price: list[float],
        performance_scores: list[float] | None = None,
        mileage: list[float] | None = None,
        perf_rate: float = 0.1,   # $/MWh
        dt_hours: float = 1.0,
    ) -> dict[str, float]:
        """
        CAISO ancillary service settlement.

        Capacity payment + mileage-based performance payment.
        """
        T = min(len(awarded_mw), len(clearing_price))
        cap_pay = np.sum(
            np.array(awarded_mw[:T]) * np.array(clearing_price[:T]) * dt_hours
        )

        perf_pay = 0.0
        if mileage and performance_scores:
            scores = np.array(performance_scores[:T])
            mile = np.array(mileage[:T])
            perf_pay = float(np.sum(mile * scores * perf_rate * dt_hours))

        return {
            "product": product,
            "capacity_payment": float(cap_pay),
            "performance_payment": float(perf_pay),
            "total_as_payment": float(cap_pay + perf_pay),
            "avg_clearing_price": float(np.mean(clearing_price[:T])),
            "n_intervals": T,
        }

    def storage_neutral_position(
        self,
        charge_mwh: list[float],
        discharge_mwh: list[float],
        ifm_lmp: list[float],
        rted_lmp: list[float],
        rte: float = 0.92,
    ) -> dict[str, float]:
        """
        Calculate CAISO storage resource neutral position analysis.

        For storage, CAISO charges/credits based on net position.
        Net position = discharge - charge (positive = net generator)

        Neutral position analysis: at what LMP spread does storage break even?
        """
        dis = np.array(discharge_mwh)
        ch = np.array(charge_mwh)
        lmp_da = np.array(ifm_lmp)
        lmp_rt = np.array(rted_lmp)

        # Break-even spread = charge_cost / (rte * discharge_efficiency)
        avg_ch_lmp = float(np.mean(lmp_da[ch > 0])) if (ch > 0).any() else 0.0
        avg_dis_lmp = float(np.mean(lmp_da[dis > 0])) if (dis > 0).any() else 0.0
        spread = avg_dis_lmp - avg_ch_lmp
        break_even = avg_ch_lmp / rte

        total_rev = float(np.sum(dis * lmp_rt - ch * lmp_rt / rte))

        return {
            "avg_charge_lmp": avg_ch_lmp,
            "avg_discharge_lmp": avg_dis_lmp,
            "avg_spread": spread,
            "break_even_lmp": break_even,
            "spread_above_breakeven": spread - break_even,
            "total_revenue": total_rev,
            "revenue_per_cycle": total_rev / max(1, int(np.sum(dis > 0.1))),
        }
