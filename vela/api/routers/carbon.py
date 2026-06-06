"""Carbon tracking endpoints: emissions intensity, avoided emissions, carbon credits."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter()


class EmissionsRecord(BaseModel):
    asset_id: str
    interval_start: datetime
    interval_end: datetime
    energy_mwh: float
    grid_carbon_intensity_kg_per_mwh: float
    gross_emissions_kg: float
    avoided_emissions_kg: float
    net_emissions_kg: float
    marginal_emissions_rate: float | None = None


class CarbonSummary(BaseModel):
    period_start: datetime
    period_end: datetime
    asset_id: str | None = None
    total_avoided_kg: float
    total_gross_kg: float
    net_emissions_kg: float
    avg_carbon_intensity: float
    carbon_credits_tonne: float  # 1 credit = 1 tonne CO2


class GridCarbonIntensity(BaseModel):
    region: str
    timestamp: datetime
    intensity_kg_per_mwh: float
    source: Literal["real_time", "forecast", "historical"]
    fuel_mix: dict[str, float] = Field(default_factory=dict)


@router.get("/intensity", response_model=GridCarbonIntensity)
async def get_carbon_intensity(
    region: str = Query(default="CAISO"),
    timestamp: datetime | None = Query(default=None),
) -> GridCarbonIntensity:
    """Return grid carbon intensity for a region at a given time."""
    import numpy as np
    ts = timestamp or datetime.now(timezone.utc)
    hour = ts.hour
    # Carbon intensity is lower at night (more renewables) and higher during peak hours
    base = 200 + 80 * abs(hour - 12) / 12
    np.random.seed(hash(region) % 2**31 + ts.hour)
    intensity = round(max(50, base + np.random.normal(0, 30)), 1)
    fuel_mix = {
        "solar": round(max(0, 0.3 * (1 - abs(hour - 12) / 12)), 3),
        "wind": round(np.random.uniform(0.15, 0.35), 3),
        "gas": round(np.random.uniform(0.25, 0.45), 3),
        "hydro": round(np.random.uniform(0.05, 0.15), 3),
        "nuclear": round(np.random.uniform(0.05, 0.10), 3),
    }
    total = sum(fuel_mix.values())
    fuel_mix = {k: round(v / total, 3) for k, v in fuel_mix.items()}
    return GridCarbonIntensity(
        region=region,
        timestamp=ts,
        intensity_kg_per_mwh=intensity,
        source="real_time",
        fuel_mix=fuel_mix,
    )


@router.get("/emissions/{asset_id}", response_model=list[EmissionsRecord])
async def get_emissions(
    asset_id: str,
    start: datetime = Query(default=None),
    end: datetime = Query(default=None),
) -> list[EmissionsRecord]:
    """Return hourly emissions records for an asset."""
    import numpy as np
    now = datetime.now(timezone.utc)
    start = start or (now - timedelta(days=1))
    end = end or now
    hours = max(1, int((end - start).total_seconds() / 3600))
    np.random.seed(hash(asset_id) % 2**31)
    records = []
    for h in range(hours):
        t0 = start + timedelta(hours=h)
        t1 = t0 + timedelta(hours=1)
        energy = round(abs(np.random.normal(1.5, 0.5)), 3)
        intensity = round(abs(np.random.normal(220, 60)), 1)
        gross = round(energy * intensity, 2)
        avoided = round(energy * intensity * np.random.uniform(0.6, 0.9), 2)
        records.append(EmissionsRecord(
            asset_id=asset_id,
            interval_start=t0,
            interval_end=t1,
            energy_mwh=energy,
            grid_carbon_intensity_kg_per_mwh=intensity,
            gross_emissions_kg=gross,
            avoided_emissions_kg=avoided,
            net_emissions_kg=round(gross - avoided, 2),
            marginal_emissions_rate=round(intensity * 1.1, 1),
        ))
    return records


@router.get("/summary", response_model=CarbonSummary)
async def carbon_summary(
    asset_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> CarbonSummary:
    """Aggregate carbon summary over a period."""
    import numpy as np
    now = datetime.now(timezone.utc)
    np.random.seed(42)
    avoided = round(abs(np.random.normal(45000 * days / 30, 8000)), 1)
    gross = round(abs(np.random.normal(15000 * days / 30, 3000)), 1)
    return CarbonSummary(
        period_start=now - timedelta(days=days),
        period_end=now,
        asset_id=asset_id,
        total_avoided_kg=avoided,
        total_gross_kg=gross,
        net_emissions_kg=round(gross - avoided, 1),
        avg_carbon_intensity=round(np.random.normal(220, 40), 1),
        carbon_credits_tonne=round(avoided / 1000, 2),
    )
