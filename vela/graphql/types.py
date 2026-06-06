"""Strawberry GraphQL type definitions for the Vela VPP API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import strawberry


@strawberry.type
class AssetType:
    asset_id: str
    asset_type: str
    capacity_mwh: Optional[float]
    power_mw: float
    status: str
    soc: Optional[float]
    site_id: Optional[str] = None


@strawberry.type
class DispatchIntervalType:
    interval_start: datetime
    asset_id: str
    charge_mw: float
    discharge_mw: float
    soc: float
    lmp: float
    revenue_usd: float


@strawberry.type
class DispatchPlanType:
    plan_id: str
    status: str
    created_at: datetime
    asset_ids: list[str]
    horizon_hours: int
    market: str
    objective_value: Optional[float]
    solve_time_s: Optional[float]
    intervals: list[DispatchIntervalType]


@strawberry.type
class ForecastPointType:
    timestamp: datetime
    mean: float
    p10: float
    p90: float


@strawberry.type
class PriceForecastType:
    forecast_id: str
    node: str
    model: str
    generated_at: datetime
    horizon_hours: int
    unit: str
    points: list[ForecastPointType]


@strawberry.type
class SettlementIntervalType:
    interval_start: datetime
    scheduled_mwh: float
    metered_mwh: float
    lmp: float
    imbalance_mwh: float
    net_revenue_usd: float


@strawberry.type
class SettlementStatementType:
    statement_id: str
    asset_id: str
    market: str
    settlement_date: datetime
    status: str
    total_revenue_usd: float
    total_imbalance_charge_usd: float
    net_revenue_usd: float


@strawberry.type
class TelemetryPointType:
    timestamp: datetime
    asset_id: str
    soc: Optional[float]
    power_mw: Optional[float]
    temperature_c: Optional[float]
    status: str


@strawberry.type
class CarbonIntensityType:
    region: str
    timestamp: datetime
    intensity_kg_per_mwh: float
    source: str


@strawberry.type
class MarketBidType:
    bid_id: str
    asset_id: str
    market: str
    service: str
    quantity_mw: float
    price_usd_mwh: float
    status: str
    submitted_at: Optional[datetime]


@strawberry.type
class SiteType:
    site_id: str
    name: str
    iso: str
    pricing_node: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    asset_ids: list[str]
    status: str


@strawberry.input
class AssetInput:
    asset_type: str
    capacity_mwh: Optional[float] = None
    power_mw: float = 1.0
    status: str = "online"
    soc: Optional[float] = None


@strawberry.input
class DispatchInput:
    asset_ids: list[str]
    horizon_hours: int = 24
    market: str = "CAISO"
    objective: str = "revenue"
