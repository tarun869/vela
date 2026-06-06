"""Shared Pydantic response/request schemas used across routers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    cursor: str | None = None
    has_more: bool = False


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class ErrorResponse(BaseModel):
    detail: str
    errors: list[ErrorDetail] = Field(default_factory=list)
    request_id: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded" | "down"
    version: str
    timestamp: datetime
    checks: dict[str, str] = Field(default_factory=dict)


class OperationResult(BaseModel):
    success: bool
    message: str
    data: dict[str, Any] | None = None


class TimeSeriesPoint(BaseModel):
    timestamp: datetime
    value: float
    unit: str | None = None


class TimeSeriesResponse(BaseModel):
    series_id: str
    label: str
    unit: str
    points: list[TimeSeriesPoint]


class IntervalBlock(BaseModel):
    """Generic interval-metered data block (1-hour or 5-minute intervals)."""
    interval_start: datetime
    interval_end: datetime
    value: float
    quality: str = "good"  # "good" | "estimated" | "invalid"


class MarketInterval(BaseModel):
    interval_start: datetime
    lmp: float
    energy_mwh: float
    revenue_usd: float
    market: str


class AssetStatus(BaseModel):
    asset_id: str
    asset_type: str
    status: str  # "online" | "offline" | "standby" | "fault"
    soc: float | None = None
    power_mw: float = 0.0
    last_updated: datetime


class DispatchInterval(BaseModel):
    interval_start: datetime
    asset_id: str
    charge_mw: float
    discharge_mw: float
    soc: float
    lmp: float
    revenue_usd: float
