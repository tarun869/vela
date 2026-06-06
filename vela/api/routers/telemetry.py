"""Telemetry endpoints: ingest and query real-time asset measurements."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class TelemetryPoint(BaseModel):
    timestamp: datetime
    asset_id: str
    soc: float | None = Field(default=None, ge=0.0, le=1.0)
    power_mw: float | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    temperature_c: float | None = None
    status: Literal["online", "offline", "standby", "fault", "unknown"] = "unknown"


class TelemetryBatch(BaseModel):
    points: list[TelemetryPoint] = Field(..., min_length=1, max_length=10_000)
    source: str = "scada"


class TelemetryIngestResponse(BaseModel):
    ingested: int
    rejected: int
    batch_id: str


class TelemetryQuery(BaseModel):
    asset_ids: list[str]
    start: datetime
    end: datetime
    fields: list[str] = Field(default_factory=lambda: ["soc", "power_mw", "status"])
    resolution_minutes: int = Field(default=5, ge=1, le=60)


_STORE: list[TelemetryPoint] = []


@router.post("/ingest", response_model=TelemetryIngestResponse, status_code=202)
async def ingest_telemetry(batch: TelemetryBatch) -> TelemetryIngestResponse:
    """Bulk-ingest telemetry measurements from SCADA or IoT sensors."""
    accepted = 0
    rejected = 0
    for point in batch.points:
        if point.asset_id and point.timestamp:
            _STORE.append(point)
            accepted += 1
        else:
            rejected += 1
    return TelemetryIngestResponse(
        ingested=accepted,
        rejected=rejected,
        batch_id=str(uuid.uuid4()),
    )


@router.get("/latest/{asset_id}", response_model=TelemetryPoint)
async def get_latest(asset_id: str) -> TelemetryPoint:
    """Return the most recent telemetry reading for an asset."""
    candidates = [p for p in _STORE if p.asset_id == asset_id]
    if not candidates:
        # Return a synthetic reading for dev/demo
        import random
        return TelemetryPoint(
            timestamp=datetime.now(timezone.utc),
            asset_id=asset_id,
            soc=round(random.uniform(0.2, 0.9), 3),
            power_mw=round(random.uniform(-2.0, 2.0), 3),
            temperature_c=round(random.uniform(20.0, 35.0), 1),
            status="online",
        )
    return sorted(candidates, key=lambda p: p.timestamp)[-1]


@router.post("/query", response_model=list[TelemetryPoint])
async def query_telemetry(request: TelemetryQuery) -> list[TelemetryPoint]:
    """Query historical telemetry for a set of assets within a time window."""
    results = [
        p for p in _STORE
        if p.asset_id in request.asset_ids
        and request.start <= p.timestamp <= request.end
    ]
    return sorted(results, key=lambda p: p.timestamp)


@router.get("/health/{asset_id}")
async def asset_health(asset_id: str) -> dict:
    """Return a brief health summary for an asset."""
    import random
    latest = await get_latest(asset_id)
    score = 1.0
    alerts: list[str] = []
    if latest.soc is not None and latest.soc < 0.1:
        score -= 0.3
        alerts.append("SOC critically low")
    if latest.temperature_c is not None and latest.temperature_c > 40:
        score -= 0.2
        alerts.append("High temperature")
    if latest.status == "fault":
        score = 0.0
        alerts.append("Asset in fault state")
    return {
        "asset_id": asset_id,
        "health_score": round(max(0.0, score), 2),
        "status": latest.status,
        "alerts": alerts,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
