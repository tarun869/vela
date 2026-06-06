"""Market obligations endpoints: capacity commitments, delivery tracking."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class ObligationCreate(BaseModel):
    asset_id: str
    obligation_type: Literal["capacity", "regulation", "spinning_reserve", "demand_response", "must_run"]
    market: str = "CAISO"
    committed_mw: float = Field(..., gt=0)
    period_start: datetime
    period_end: datetime
    price_usd_mwh: float | None = None
    contract_id: str | None = None


class Obligation(BaseModel):
    obligation_id: str
    asset_id: str
    obligation_type: str
    market: str
    committed_mw: float
    period_start: datetime
    period_end: datetime
    price_usd_mwh: float | None
    contract_id: str | None
    status: Literal["active", "expired", "cancelled", "pending"]
    created_at: datetime
    delivered_mw: float = 0.0
    compliance_pct: float = 1.0


class DeliveryRecord(BaseModel):
    obligation_id: str
    interval_start: datetime
    delivered_mw: float
    shortfall_mw: float
    penalty_usd: float
    notes: str | None = None


_OBLIGATIONS: dict[str, Obligation] = {}
_DELIVERIES: list[DeliveryRecord] = []


@router.post("/", response_model=Obligation, status_code=201)
async def create_obligation(request: ObligationCreate) -> Obligation:
    ob = Obligation(
        obligation_id=str(uuid.uuid4()),
        asset_id=request.asset_id,
        obligation_type=request.obligation_type,
        market=request.market,
        committed_mw=request.committed_mw,
        period_start=request.period_start,
        period_end=request.period_end,
        price_usd_mwh=request.price_usd_mwh,
        contract_id=request.contract_id,
        status="active",
        created_at=datetime.now(timezone.utc),
    )
    _OBLIGATIONS[ob.obligation_id] = ob
    return ob


@router.get("/", response_model=list[Obligation])
async def list_obligations(
    asset_id: str | None = Query(default=None),
    market: str | None = Query(default=None),
    status: str | None = Query(default=None),
    active_only: bool = Query(default=False),
) -> list[Obligation]:
    obs = list(_OBLIGATIONS.values())
    if asset_id:
        obs = [o for o in obs if o.asset_id == asset_id]
    if market:
        obs = [o for o in obs if o.market == market]
    if status:
        obs = [o for o in obs if o.status == status]
    if active_only:
        now = datetime.now(timezone.utc)
        obs = [o for o in obs if o.status == "active" and o.period_start <= now <= o.period_end]
    return obs


@router.get("/{obligation_id}", response_model=Obligation)
async def get_obligation(obligation_id: str) -> Obligation:
    ob = _OBLIGATIONS.get(obligation_id)
    if not ob:
        raise HTTPException(status_code=404, detail=f"Obligation {obligation_id} not found")
    return ob


@router.post("/{obligation_id}/cancel", response_model=Obligation)
async def cancel_obligation(obligation_id: str) -> Obligation:
    ob = _OBLIGATIONS.get(obligation_id)
    if not ob:
        raise HTTPException(status_code=404, detail=f"Obligation {obligation_id} not found")
    if ob.status not in ("active", "pending"):
        raise HTTPException(status_code=409, detail=f"Cannot cancel obligation in status '{ob.status}'")
    ob.status = "cancelled"
    return ob


@router.post("/{obligation_id}/record_delivery", response_model=DeliveryRecord, status_code=201)
async def record_delivery(
    obligation_id: str,
    delivered_mw: float = Query(..., ge=0),
    interval_start: datetime = Query(default=None),
) -> DeliveryRecord:
    ob = _OBLIGATIONS.get(obligation_id)
    if not ob:
        raise HTTPException(status_code=404, detail=f"Obligation {obligation_id} not found")
    now = datetime.now(timezone.utc)
    shortfall = max(0.0, ob.committed_mw - delivered_mw)
    penalty_rate = (ob.price_usd_mwh or 50.0) * 2.0  # typical penalty is 2x clearing price
    penalty = round(shortfall * penalty_rate, 2)
    record = DeliveryRecord(
        obligation_id=obligation_id,
        interval_start=interval_start or now,
        delivered_mw=delivered_mw,
        shortfall_mw=round(shortfall, 3),
        penalty_usd=penalty,
    )
    _DELIVERIES.append(record)
    # Update compliance
    ob.delivered_mw = delivered_mw
    ob.compliance_pct = round(min(1.0, delivered_mw / ob.committed_mw), 4)
    return record


@router.get("/{obligation_id}/deliveries", response_model=list[DeliveryRecord])
async def get_deliveries(obligation_id: str) -> list[DeliveryRecord]:
    return [d for d in _DELIVERIES if d.obligation_id == obligation_id]
