"""Market bid management endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class BidRequest(BaseModel):
    asset_id: str
    market: str = Field(default="CAISO", description="Market (CAISO, ERCOT, PJM, MISO)")
    service: Literal["energy", "reg_up", "reg_down", "spin", "non_spin"] = "energy"
    quantity_mw: float = Field(..., gt=0)
    price_usd_mwh: float = Field(..., ge=0)
    interval_start: datetime
    interval_end: datetime


class BidResponse(BaseModel):
    bid_id: str
    asset_id: str
    market: str
    service: str
    quantity_mw: float
    price_usd_mwh: float
    interval_start: datetime
    interval_end: datetime
    status: Literal["draft", "submitted", "accepted", "rejected", "partially_accepted"]
    submitted_at: datetime | None = None
    cleared_mw: float | None = None
    cleared_price: float | None = None


class MarketPrice(BaseModel):
    node: str
    market: str
    service: str
    interval_start: datetime
    lmp: float
    energy_component: float
    congestion_component: float
    loss_component: float


_BIDS: dict[str, BidResponse] = {}


@router.post("/bids", response_model=BidResponse, status_code=201)
async def create_bid(request: BidRequest) -> BidResponse:
    """Create a new market bid."""
    bid_id = str(uuid.uuid4())
    bid = BidResponse(
        bid_id=bid_id,
        asset_id=request.asset_id,
        market=request.market,
        service=request.service,
        quantity_mw=request.quantity_mw,
        price_usd_mwh=request.price_usd_mwh,
        interval_start=request.interval_start,
        interval_end=request.interval_end,
        status="draft",
    )
    _BIDS[bid_id] = bid
    return bid


@router.get("/bids", response_model=list[BidResponse])
async def list_bids(
    asset_id: str | None = Query(default=None),
    market: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[BidResponse]:
    bids = list(_BIDS.values())
    if asset_id:
        bids = [b for b in bids if b.asset_id == asset_id]
    if market:
        bids = [b for b in bids if b.market == market]
    if status:
        bids = [b for b in bids if b.status == status]
    return bids[-limit:]


@router.get("/bids/{bid_id}", response_model=BidResponse)
async def get_bid(bid_id: str) -> BidResponse:
    bid = _BIDS.get(bid_id)
    if not bid:
        raise HTTPException(status_code=404, detail=f"Bid {bid_id} not found")
    return bid


@router.post("/bids/{bid_id}/submit", response_model=BidResponse)
async def submit_bid(bid_id: str) -> BidResponse:
    """Submit a draft bid to the market."""
    bid = _BIDS.get(bid_id)
    if not bid:
        raise HTTPException(status_code=404, detail=f"Bid {bid_id} not found")
    if bid.status != "draft":
        raise HTTPException(status_code=409, detail=f"Bid must be in 'draft' status; got '{bid.status}'")
    bid.status = "submitted"
    bid.submitted_at = datetime.now(timezone.utc)
    return bid


@router.delete("/bids/{bid_id}", status_code=204)
async def cancel_bid(bid_id: str) -> None:
    if bid_id not in _BIDS:
        raise HTTPException(status_code=404, detail=f"Bid {bid_id} not found")
    del _BIDS[bid_id]


@router.get("/prices", response_model=list[MarketPrice])
async def get_market_prices(
    node: str = Query(default="TH_NP15_GEN-APND"),
    market: str = Query(default="CAISO"),
    hours: int = Query(default=24, ge=1, le=168),
) -> list[MarketPrice]:
    """Return recent LMP data for a pricing node."""
    import numpy as np
    from datetime import timedelta

    np.random.seed(0)
    now = datetime.now(timezone.utc)
    daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
    prices = []
    for h in range(hours):
        base = daily[h % 24]
        lmp = round(base + np.random.normal(0, 4), 2)
        energy = round(lmp * 0.85, 2)
        congestion = round(lmp * 0.10, 2)
        loss = round(lmp - energy - congestion, 2)
        prices.append(MarketPrice(
            node=node,
            market=market,
            service="energy",
            interval_start=now - timedelta(hours=hours - h),
            lmp=lmp,
            energy_component=energy,
            congestion_component=congestion,
            loss_component=loss,
        ))
    return prices
