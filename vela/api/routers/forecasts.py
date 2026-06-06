"""Forecast endpoints: price, load, solar, and ancillary service forecasts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class ForecastRequest(BaseModel):
    node: str = Field(default="TH_NP15_GEN-APND", description="Pricing node or bus ID")
    horizon_hours: int = Field(default=24, ge=1, le=168)
    model: str = Field(default="ar", description="Model type: ar | xgb | lstm | ensemble")
    history_hours: int = Field(default=168, description="Hours of history to use for fitting")


class ForecastPoint(BaseModel):
    timestamp: datetime
    mean: float
    p10: float
    p90: float


class ForecastResponse(BaseModel):
    forecast_id: str
    node: str
    model: str
    generated_at: datetime
    horizon_hours: int
    unit: str
    points: list[ForecastPoint]


class LoadForecastResponse(BaseModel):
    forecast_id: str
    site_id: str
    generated_at: datetime
    horizon_hours: int
    points: list[ForecastPoint]


@router.post("/price", response_model=ForecastResponse)
async def forecast_price(request: ForecastRequest) -> ForecastResponse:
    """Generate an LMP price forecast using the AR model."""
    from vela.m5_forecasting.price_forecast import ARPriceModel
    import uuid
    import numpy as np

    # Simulate recent history with a plausible daily pattern
    np.random.seed(42)
    daily_pattern = [
        25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
        50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38,
    ]
    history = []
    for _ in range(request.history_hours // 24 + 1):
        history.extend([max(0.0, p + np.random.normal(0, 5)) for p in daily_pattern])
    history = history[: request.history_hours]

    model = ARPriceModel(lags=min(24, len(history) - 1))
    model.fit(history)
    forecast = model.predict(recent=history, horizon=request.horizon_hours)

    points = [
        ForecastPoint(timestamp=ts, mean=round(m, 2), p10=round(p10, 2), p90=round(p90, 2))
        for ts, m, p10, p90 in zip(forecast.timestamps, forecast.mean, forecast.p10, forecast.p90)
    ]
    return ForecastResponse(
        forecast_id=str(uuid.uuid4()),
        node=request.node,
        model=request.model,
        generated_at=datetime.now(timezone.utc),
        horizon_hours=request.horizon_hours,
        unit="$/MWh",
        points=points,
    )


@router.get("/price/{node}", response_model=ForecastResponse)
async def get_latest_price_forecast(
    node: str,
    horizon_hours: int = Query(default=24, ge=1, le=168),
) -> ForecastResponse:
    """Return the most recently generated price forecast for a node."""
    # In production, fetch from DB; here we generate on-the-fly
    req = ForecastRequest(node=node, horizon_hours=horizon_hours)
    return await forecast_price(req)


@router.post("/load", response_model=LoadForecastResponse)
async def forecast_load(
    site_id: str = Query(..., description="Site or meter ID"),
    horizon_hours: int = Query(default=24, ge=1, le=168),
) -> LoadForecastResponse:
    """Generate a load forecast for a site."""
    import uuid
    import numpy as np

    np.random.seed(12)
    base_pattern = [0.8, 0.7, 0.65, 0.6, 0.62, 0.7, 1.0, 1.3, 1.5, 1.5, 1.4, 1.3,
                    1.2, 1.2, 1.3, 1.4, 1.5, 1.6, 1.5, 1.4, 1.2, 1.1, 1.0, 0.9]
    now = datetime.now(timezone.utc)
    points = []
    for h in range(horizon_hours):
        base = base_pattern[h % 24]
        mean = round(base + np.random.normal(0, 0.05), 3)
        points.append(ForecastPoint(
            timestamp=now + timedelta(hours=h),
            mean=mean,
            p10=round(mean * 0.9, 3),
            p90=round(mean * 1.1, 3),
        ))
    return LoadForecastResponse(
        forecast_id=str(uuid.uuid4()),
        site_id=site_id,
        generated_at=now,
        horizon_hours=horizon_hours,
        points=points,
    )


@router.get("/ancillary", response_model=ForecastResponse)
async def forecast_ancillary(
    service: str = Query(default="reg_up", description="reg_up | reg_down | spin | non_spin"),
    node: str = Query(default="TH_NP15_GEN-APND"),
    horizon_hours: int = Query(default=24, ge=1, le=48),
) -> ForecastResponse:
    """Forecast ancillary service prices."""
    import uuid
    import numpy as np

    service_multipliers = {"reg_up": 1.5, "reg_down": 0.8, "spin": 1.2, "non_spin": 0.6}
    mult = service_multipliers.get(service, 1.0)
    np.random.seed(7)
    now = datetime.now(timezone.utc)
    points = []
    base = 15.0 * mult
    for h in range(horizon_hours):
        mean = round(max(0, base + np.random.normal(0, 3)), 2)
        points.append(ForecastPoint(
            timestamp=now + timedelta(hours=h),
            mean=mean,
            p10=round(mean * 0.8, 2),
            p90=round(mean * 1.3, 2),
        ))
    return ForecastResponse(
        forecast_id=str(uuid.uuid4()),
        node=node,
        model="ar",
        generated_at=now,
        horizon_hours=horizon_hours,
        unit="$/MWh",
        points=points,
    )
