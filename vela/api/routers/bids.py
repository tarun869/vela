"""Bid management endpoints: day-ahead and real-time bidding workflow."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class BidStack(BaseModel):
    """A price-quantity bid stack for a single asset and interval."""
    stack_id: str
    asset_id: str
    market: str
    service: Literal["energy", "reg_up", "reg_down", "spin", "non_spin"]
    interval_start: datetime
    interval_end: datetime
    tranches: list[dict]  # [{"mw": float, "price": float}]
    status: Literal["draft", "submitted", "cleared", "rejected"]
    created_at: datetime


class BidOptimizeRequest(BaseModel):
    """Request to auto-generate a bid stack from the optimizer output."""
    asset_id: str
    plan_id: str | None = None  # Reference to a dispatch plan
    market: str = "CAISO"
    services: list[str] = Field(default_factory=lambda: ["energy", "reg_up"])
    target_date: datetime | None = None
    risk_tolerance: Literal["conservative", "moderate", "aggressive"] = "moderate"


class ClearingResult(BaseModel):
    stack_id: str
    cleared_mw: float
    cleared_price: float
    market_revenue_usd: float
    cleared_at: datetime


_STACKS: dict[str, BidStack] = {}
_CLEARINGS: dict[str, ClearingResult] = {}


@router.post("/stacks", response_model=BidStack, status_code=201)
async def create_bid_stack(
    asset_id: str = Query(...),
    market: str = Query(default="CAISO"),
    service: str = Query(default="energy"),
    interval_start: datetime = Query(...),
    interval_end: datetime = Query(...),
    tranches: str = Query(default="[]", description="JSON list of {mw, price} dicts"),
) -> BidStack:
    import json
    try:
        tranches_parsed = json.loads(tranches)
    except Exception:
        tranches_parsed = []

    stack = BidStack(
        stack_id=str(uuid.uuid4()),
        asset_id=asset_id,
        market=market,
        service=service,  # type: ignore[arg-type]
        interval_start=interval_start,
        interval_end=interval_end,
        tranches=tranches_parsed,
        status="draft",
        created_at=datetime.now(timezone.utc),
    )
    _STACKS[stack.stack_id] = stack
    return stack


@router.post("/optimize", response_model=BidStack, status_code=201)
async def optimize_bids(request: BidOptimizeRequest) -> BidStack:
    """Auto-generate a bid stack based on price forecast and optimizer output."""
    from datetime import timedelta
    import numpy as np
    np.random.seed(42)

    now = datetime.now(timezone.utc)
    target = request.target_date or now
    n_tranches = 5
    capacity = 2.0
    tranche_mw = capacity / n_tranches
    multipliers = {"conservative": 1.2, "moderate": 1.0, "aggressive": 0.8}
    m = multipliers[request.risk_tolerance]
    tranches = [
        {"mw": round(tranche_mw, 3), "price": round(30 + 20 * i * m + np.random.normal(0, 2), 2)}
        for i in range(n_tranches)
    ]
    stack = BidStack(
        stack_id=str(uuid.uuid4()),
        asset_id=request.asset_id,
        market=request.market,
        service="energy",
        interval_start=target,
        interval_end=target + timedelta(hours=1),
        tranches=tranches,
        status="draft",
        created_at=now,
    )
    _STACKS[stack.stack_id] = stack
    return stack


@router.get("/stacks", response_model=list[BidStack])
async def list_stacks(
    asset_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[BidStack]:
    stacks = list(_STACKS.values())
    if asset_id:
        stacks = [s for s in stacks if s.asset_id == asset_id]
    if status:
        stacks = [s for s in stacks if s.status == status]
    return stacks


@router.get("/stacks/{stack_id}", response_model=BidStack)
async def get_stack(stack_id: str) -> BidStack:
    stack = _STACKS.get(stack_id)
    if not stack:
        raise HTTPException(status_code=404, detail=f"Bid stack {stack_id} not found")
    return stack


@router.post("/stacks/{stack_id}/submit", response_model=BidStack)
async def submit_stack(stack_id: str) -> BidStack:
    stack = _STACKS.get(stack_id)
    if not stack:
        raise HTTPException(status_code=404, detail=f"Bid stack {stack_id} not found")
    if stack.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft stacks can be submitted")
    stack.status = "submitted"
    return stack


@router.get("/clearings", response_model=list[ClearingResult])
async def list_clearings() -> list[ClearingResult]:
    return list(_CLEARINGS.values())
