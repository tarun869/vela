"""Revenue attribution by service, asset, and market for portfolio analysis."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import NamedTuple


class RevenueAttribution(NamedTuple):
    asset_id: str
    period: str
    energy_arbitrage: float
    reg_up: float
    reg_down: float
    spin: float
    capacity: float
    dr_performance: float
    total: float
    as_fraction: float
    energy_fraction: float


@dataclass
class RevenueAttributor:
    """
    Attributes VPP revenue to individual services and time periods.

    Used for:
    - Portfolio reporting and analytics
    - Identifying highest-value services
    - Comparing performance across assets
    - Regulatory reporting (some markets require service-level reporting)
    """

    def attribute(
        self,
        asset_id: str,
        period: str,
        charge_mw: list[float],
        discharge_mw: list[float],
        lmp: list[float],
        reg_up_mw: list[float] | None = None,
        reg_up_price: list[float] | None = None,
        reg_down_mw: list[float] | None = None,
        reg_down_price: list[float] | None = None,
        spin_mw: list[float] | None = None,
        spin_price: list[float] | None = None,
        capacity_revenue: float = 0.0,
        dr_performance_revenue: float = 0.0,
        rte: float = 0.92,
        dt_hours: float = 1.0,
    ) -> RevenueAttribution:
        """
        Attribute revenue to each service type.

        Energy arbitrage = (discharge * lmp - charge * lmp / rte) * dt
        AS revenue = service_mw * service_price * dt
        """
        T = len(lmp)
        ch = np.array(charge_mw[:T])
        dis = np.array(discharge_mw[:T])
        lmp_arr = np.array(lmp[:T])

        energy_rev = float(np.sum((dis * lmp_arr - ch * lmp_arr / rte) * dt_hours))

        ru_rev = 0.0
        rd_rev = 0.0
        sp_rev = 0.0

        if reg_up_mw and reg_up_price:
            ru_arr = np.array(reg_up_mw[:T])
            rup_arr = np.array(reg_up_price[:T])
            ru_rev = float(np.sum(ru_arr * rup_arr * dt_hours))

        if reg_down_mw and reg_down_price:
            rd_arr = np.array(reg_down_mw[:T])
            rdp_arr = np.array(reg_down_price[:T])
            rd_rev = float(np.sum(rd_arr * rdp_arr * dt_hours))

        if spin_mw and spin_price:
            sp_arr = np.array(spin_mw[:T])
            spp_arr = np.array(spin_price[:T])
            sp_rev = float(np.sum(sp_arr * spp_arr * dt_hours))

        as_total = ru_rev + rd_rev + sp_rev
        total = energy_rev + as_total + capacity_revenue + dr_performance_revenue
        total_abs = abs(total) + 1e-6

        return RevenueAttribution(
            asset_id=asset_id,
            period=period,
            energy_arbitrage=energy_rev,
            reg_up=ru_rev,
            reg_down=rd_rev,
            spin=sp_rev,
            capacity=capacity_revenue,
            dr_performance=dr_performance_revenue,
            total=total,
            as_fraction=as_total / total_abs,
            energy_fraction=energy_rev / total_abs,
        )

    def portfolio_summary(
        self,
        attributions: list[RevenueAttribution],
    ) -> dict[str, float]:
        """Aggregate revenue attribution across multiple assets."""
        if not attributions:
            return {}
        totals = {
            "energy_arbitrage": sum(a.energy_arbitrage for a in attributions),
            "reg_up": sum(a.reg_up for a in attributions),
            "reg_down": sum(a.reg_down for a in attributions),
            "spin": sum(a.spin for a in attributions),
            "capacity": sum(a.capacity for a in attributions),
            "dr_performance": sum(a.dr_performance for a in attributions),
            "total": sum(a.total for a in attributions),
        }
        totals["as_fraction"] = (
            (totals["reg_up"] + totals["reg_down"] + totals["spin"])
            / (totals["total"] + 1e-6)
        )
        totals["best_asset"] = max(attributions, key=lambda a: a.total).asset_id  # type: ignore[assignment]
        return totals

    def hourly_revenue_decomposition(
        self,
        charge_mw: list[float],
        discharge_mw: list[float],
        lmp: list[float],
        reg_up_mw: list[float] | None = None,
        reg_up_price: list[float] | None = None,
        dt_hours: float = 1.0,
        rte: float = 0.92,
    ) -> dict[str, list[float]]:
        """
        Compute hourly revenue breakdown for time-series analysis.
        """
        T = len(lmp)
        ch = np.array(charge_mw[:T])
        dis = np.array(discharge_mw[:T])
        lmp_arr = np.array(lmp[:T])

        energy_hourly = ((dis * lmp_arr - ch * lmp_arr / rte) * dt_hours).tolist()
        as_hourly = [0.0] * T
        if reg_up_mw and reg_up_price:
            ru = np.array(reg_up_mw[:T])
            rup = np.array(reg_up_price[:T])
            as_hourly = (ru * rup * dt_hours).tolist()

        total_hourly = [e + a for e, a in zip(energy_hourly, as_hourly)]
        cumulative = np.cumsum(total_hourly).tolist()

        return {
            "energy": energy_hourly,
            "ancillary": as_hourly,
            "total": total_hourly,
            "cumulative": cumulative,
        }
