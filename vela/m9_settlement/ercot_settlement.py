"""ERCOT settlement calculations including SCED, DAM, and AS settlement."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class ERCOTInterval(NamedTuple):
    interval_start: datetime
    dam_schedule_mwh: float         # Day-ahead market schedule
    sced_dispatch_mwh: float        # Real-time SCED dispatch (15-min)
    dam_spp: float                  # DAM Settlement Point Price ($/MWh)
    rt_spp: float                   # Real-time SPP (15-min)
    dam_revenue: float
    rt_deviation_revenue: float
    total_revenue: float
    make_whole_payment: float = 0.0  # ORDC (Operating Reserve Demand Curve) uplift


class ERCOTASSettlement(NamedTuple):
    asset_id: str
    product: str
    period: str
    cleared_mwh: float          # MW * hours cleared
    mcpc: float                 # Market Clearing Price for Capacity ($/MWh)
    deployment_mwh: float       # Actual energy deployed when called
    deployment_price: float     # $/MWh for deployment energy
    capacity_revenue: float     # cleared_mwh * mcpc
    deployment_revenue: float   # deployment * deployment_price
    total_revenue: float


@dataclass
class ERCOTSettlementEngine:
    """
    ERCOT settlement engine for storage resources (ESRs).

    ERCOT settlement structure:
    1. DAM (Day-Ahead Market): Optional participation — energy + AS
    2. SCED (Security Constrained Economic Dispatch): Real-time 15-min dispatch
    3. ORDC (Operating Reserve Demand Curve): Scarcity pricing uplift

    Settlement flow:
    - DAM energy: schedule * DAM_SPP
    - SCED deviation: (RT - DAM) * RT_SPP
    - AS capacity: cleared_mw * MCPC * hours
    - AS deployment: deployed_mwh * RT_SPP when activated

    Note: ERCOT prices can reach $9,000/MWh (HCAP) during scarcity.
    """
    asset_id: str
    qse_id: str = ""
    settlement_zone: str = "HB_NORTH"

    def calculate_energy_settlement(
        self,
        dam_schedule: list[float],
        sced_dispatch: list[float],
        dam_spp: list[float],
        rt_spp: list[float],
        ordc_uplift: list[float] | None = None,
        start_time: datetime | None = None,
        dt_hours: float = 0.25,  # ERCOT SCED is 15-minute
    ) -> list[ERCOTInterval]:
        """
        Compute ERCOT two-settlement energy revenue.

        Parameters
        ----------
        dam_schedule : list[float]
            DAM scheduled output (MW) per interval
        sced_dispatch : list[float]
            SCED dispatched output (MW) per interval (15-min)
        dam_spp : list[float]
            Day-ahead Settlement Point Price ($/MWh) — hourly
        rt_spp : list[float]
            Real-time SPP ($/MWh) — 15-min intervals
        ordc_uplift : list[float], optional
            ORDC adder ($/MWh) — scarcity premium
        """
        if start_time is None:
            start_time = datetime.utcnow().replace(minute=0, second=0, microsecond=0)

        T = min(len(sced_dispatch), len(rt_spp))
        ordc = ordc_uplift or [0.0] * T
        intervals = []

        for t in range(T):
            ts = start_time + timedelta(hours=t * dt_hours)
            # DAM is hourly; match to interval
            da_hour = int(t * dt_hours)
            dam_idx = min(da_hour, len(dam_schedule) - 1)
            dam_idx_spp = min(da_hour, len(dam_spp) - 1)

            dam_mwh = dam_schedule[dam_idx] * dt_hours
            sced_mwh = sced_dispatch[t] * dt_hours

            # ERCOT settlement: DAM at DAM SPP, SCED deviation at RT SPP
            dam_rev = dam_mwh * dam_spp[dam_idx_spp]
            rt_dev_rev = (sced_mwh - dam_mwh) * (rt_spp[t] + ordc[t])
            mwp = sced_mwh * ordc[t]  # Make-whole ORDC payment
            total = dam_rev + rt_dev_rev

            intervals.append(ERCOTInterval(
                interval_start=ts,
                dam_schedule_mwh=dam_mwh,
                sced_dispatch_mwh=sced_mwh,
                dam_spp=dam_spp[dam_idx_spp],
                rt_spp=rt_spp[t],
                dam_revenue=dam_rev,
                rt_deviation_revenue=rt_dev_rev,
                total_revenue=total,
                make_whole_payment=mwp,
            ))

        total_rev = sum(i.total_revenue for i in intervals)
        logger.info("ERCOT energy settlement %s: total=$%.2f over %d intervals", self.asset_id, total_rev, T)
        return intervals

    def calculate_as_settlement(
        self,
        product: str,
        cleared_mw: list[float],
        mcpc: list[float],           # $/MWh clearing price for capacity
        deployment_intervals: list[bool],  # Whether AS was deployed each interval
        rt_spp: list[float],
        dt_hours: float = 1.0,
    ) -> ERCOTASSettlement:
        """
        ERCOT ancillary service settlement.

        Capacity payment: cleared_MW * MCPC * dt (for being available)
        Deployment payment: RT_SPP * dt (when actually deployed)
        """
        T = min(len(cleared_mw), len(mcpc))
        deployment_count = sum(deployment_intervals[:T])

        cap_rev = sum(
            cleared_mw[t] * mcpc[t] * dt_hours
            for t in range(T)
        )

        # Deployment: when activated, receive energy payment at RT_SPP
        deploy_rev = 0.0
        deploy_mwh = 0.0
        avg_deploy_price = 0.0
        for t in range(T):
            if t < len(deployment_intervals) and deployment_intervals[t]:
                mwh = cleared_mw[t] * dt_hours
                price = rt_spp[t] if t < len(rt_spp) else mcpc[t]
                deploy_rev += mwh * price
                deploy_mwh += mwh
                avg_deploy_price += price

        avg_deploy_price = avg_deploy_price / (deployment_count + 1e-6)
        period = "N/A"

        return ERCOTASSettlement(
            asset_id=self.asset_id,
            product=product,
            period=period,
            cleared_mwh=float(sum(cleared_mw[:T])) * dt_hours,
            mcpc=float(np.mean(mcpc[:T])),
            deployment_mwh=deploy_mwh,
            deployment_price=avg_deploy_price,
            capacity_revenue=cap_rev,
            deployment_revenue=deploy_rev,
            total_revenue=cap_rev + deploy_rev,
        )

    def settlement_summary(
        self,
        energy_intervals: list[ERCOTInterval],
        as_settlements: list[ERCOTASSettlement] | None = None,
    ) -> dict[str, float]:
        """Aggregate all ERCOT settlement components."""
        energy_rev = sum(i.total_revenue for i in energy_intervals)
        dam_rev = sum(i.dam_revenue for i in energy_intervals)
        rt_rev = sum(i.rt_deviation_revenue for i in energy_intervals)
        ordc_rev = sum(i.make_whole_payment for i in energy_intervals)
        as_rev = sum(s.total_revenue for s in (as_settlements or []))

        return {
            "total_revenue": energy_rev + as_rev,
            "dam_energy_revenue": dam_rev,
            "rt_energy_revenue": rt_rev,
            "ordc_revenue": ordc_rev,
            "as_revenue": as_rev,
            "as_fraction": as_rev / (energy_rev + as_rev + 1e-6),
            "avg_rt_spp": float(np.mean([i.rt_spp for i in energy_intervals])) if energy_intervals else 0.0,
            "avg_dam_spp": float(np.mean([i.dam_spp for i in energy_intervals])) if energy_intervals else 0.0,
            "n_intervals": float(len(energy_intervals)),
        }

    def ancillary_clawback_analysis(
        self,
        as_settlements: list[ERCOTASSettlement],
        energy_price_during_deployment: list[float],
    ) -> dict[str, float]:
        """
        Analyze whether deployed AS reduced net energy revenue.

        When called for AS deployment, the resource may receive less energy
        arbitrage revenue — the "opportunity cost" of AS.
        """
        total_as_rev = sum(s.total_revenue for s in as_settlements)
        total_deploy_mwh = sum(s.deployment_mwh for s in as_settlements)

        # Opportunity cost: energy arbitrage that couldn't happen during deployment
        avg_energy_price = float(np.mean(energy_price_during_deployment)) if energy_price_during_deployment else 35.0
        opportunity_cost = total_deploy_mwh * avg_energy_price * 0.3  # Simplified

        net_as_value = total_as_rev - opportunity_cost

        return {
            "gross_as_revenue": total_as_rev,
            "deployment_opportunity_cost": opportunity_cost,
            "net_as_value": net_as_value,
            "as_roi": net_as_value / (total_deploy_mwh + 1e-6),
        }
