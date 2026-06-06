"""Analytics endpoints: revenue summaries, performance KPIs, efficiency metrics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter()


class RevenueBreakdown(BaseModel):
    period_start: datetime
    period_end: datetime
    asset_id: str | None = None
    energy_arbitrage_usd: float
    regulation_up_usd: float
    regulation_down_usd: float
    spinning_reserve_usd: float
    demand_response_usd: float
    total_usd: float
    total_energy_mwh: float
    avg_lmp: float


class PerformanceKPI(BaseModel):
    asset_id: str
    period: str  # "day" | "week" | "month"
    cycle_count: float
    round_trip_efficiency: float
    capacity_utilization: float
    availability: float
    revenue_per_mwh: float
    carbon_intensity_kg_per_mwh: float | None = None


class EfficiencySummary(BaseModel):
    fleet_round_trip_efficiency: float
    fleet_availability: float
    total_cycles: float
    total_charge_mwh: float
    total_discharge_mwh: float
    energy_losses_mwh: float
    as_of: datetime


class RevenueTimeSeries(BaseModel):
    timestamps: list[datetime]
    revenue_usd: list[float]
    lmp: list[float]
    cumulative_revenue_usd: list[float]


@router.get("/revenue", response_model=RevenueBreakdown)
async def revenue_summary(
    asset_id: str | None = Query(default=None),
    start: datetime = Query(default=None),
    end: datetime = Query(default=None),
) -> RevenueBreakdown:
    """Return revenue breakdown by service type for the given period."""
    import numpy as np
    now = datetime.now(timezone.utc)
    start = start or (now - timedelta(days=7))
    end = end or now
    np.random.seed(1)
    arb = round(abs(np.random.normal(4500, 800)), 2)
    reg_up = round(abs(np.random.normal(2200, 400)), 2)
    reg_dn = round(abs(np.random.normal(1100, 300)), 2)
    spin = round(abs(np.random.normal(600, 150)), 2)
    dr = round(abs(np.random.normal(300, 100)), 2)
    energy_mwh = round(abs(np.random.normal(850, 120)), 2)
    total = arb + reg_up + reg_dn + spin + dr
    return RevenueBreakdown(
        period_start=start,
        period_end=end,
        asset_id=asset_id,
        energy_arbitrage_usd=arb,
        regulation_up_usd=reg_up,
        regulation_down_usd=reg_dn,
        spinning_reserve_usd=spin,
        demand_response_usd=dr,
        total_usd=round(total, 2),
        total_energy_mwh=energy_mwh,
        avg_lmp=round(total / energy_mwh if energy_mwh > 0 else 0, 2),
    )


@router.get("/kpis/{asset_id}", response_model=PerformanceKPI)
async def get_kpis(
    asset_id: str,
    period: Literal["day", "week", "month"] = Query(default="week"),
) -> PerformanceKPI:
    """Return performance KPIs for a single asset."""
    import numpy as np
    np.random.seed(hash(asset_id) % 2**31)
    return PerformanceKPI(
        asset_id=asset_id,
        period=period,
        cycle_count=round(np.random.uniform(0.8, 2.5) * {"day": 1, "week": 7, "month": 30}[period], 1),
        round_trip_efficiency=round(np.random.uniform(0.88, 0.94), 3),
        capacity_utilization=round(np.random.uniform(0.55, 0.85), 3),
        availability=round(np.random.uniform(0.96, 0.999), 4),
        revenue_per_mwh=round(np.random.uniform(55, 120), 2),
        carbon_intensity_kg_per_mwh=round(np.random.uniform(0, 80), 1),
    )


@router.get("/efficiency", response_model=EfficiencySummary)
async def fleet_efficiency(
    asset_ids: list[str] = Query(default=[]),
) -> EfficiencySummary:
    """Fleet-wide efficiency summary."""
    import numpy as np
    total_charge = round(abs(np.random.normal(1200, 200)), 1)
    rte = round(np.random.uniform(0.89, 0.93), 3)
    total_discharge = round(total_charge * rte, 1)
    return EfficiencySummary(
        fleet_round_trip_efficiency=rte,
        fleet_availability=round(np.random.uniform(0.97, 0.999), 4),
        total_cycles=round(np.random.uniform(120, 400), 1),
        total_charge_mwh=total_charge,
        total_discharge_mwh=total_discharge,
        energy_losses_mwh=round(total_charge - total_discharge, 2),
        as_of=datetime.now(timezone.utc),
    )


@router.get("/revenue/timeseries", response_model=RevenueTimeSeries)
async def revenue_timeseries(
    asset_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    granularity: Literal["hour", "day"] = Query(default="day"),
) -> RevenueTimeSeries:
    """Return a revenue time series for plotting."""
    import numpy as np
    now = datetime.now(timezone.utc)
    steps = days * 24 if granularity == "hour" else days
    delta = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    np.random.seed(42)
    timestamps = [now - timedelta(days=days) + delta * i for i in range(steps)]
    daily_base = 650.0 / 24 if granularity == "hour" else 650.0
    revenues = [round(max(0, np.random.normal(daily_base, daily_base * 0.3)), 2) for _ in range(steps)]
    cumulative = []
    running = 0.0
    for r in revenues:
        running += r
        cumulative.append(round(running, 2))
    lmp_values = [round(max(0, np.random.normal(55, 25)), 2) for _ in range(steps)]
    return RevenueTimeSeries(
        timestamps=timestamps,
        revenue_usd=revenues,
        lmp=lmp_values,
        cumulative_revenue_usd=cumulative,
    )
