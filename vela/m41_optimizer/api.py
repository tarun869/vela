"""FastAPI router for the heuristic dispatch engine."""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from vela.m39_extraction.models import DeliveryWindow, ExtractedObligation, ObligationType
from vela.m40_telemetry.api import get_fleet

from .heuristic import HeuristicOptimizer
from .scheduler import DispatchScheduler

logger = logging.getLogger(__name__)

router = APIRouter()

# Process-wide active scheduler.
_scheduler: DispatchScheduler | None = None


def get_scheduler() -> DispatchScheduler | None:
    return _scheduler


def set_scheduler(scheduler: DispatchScheduler | None) -> None:
    """Test/seam hook to inject or reset the active scheduler."""
    global _scheduler
    _scheduler = scheduler


class ObligationIn(BaseModel):
    """A market commitment the operator enrolled the fleet into."""

    obligation_type: ObligationType = "capacity"
    committed_mw: float
    start_hour: int = Field(default=16, ge=0, le=23)
    end_hour: int = Field(default=20, ge=0, le=23)
    penalty_linear_per_mwh: float | None = 1000.0

    def to_obligation(self) -> ExtractedObligation:
        return ExtractedObligation(
            obligation_type=self.obligation_type,
            committed_mw=self.committed_mw,
            delivery_windows=[
                DeliveryWindow(days=["All"], start_hour=self.start_hour, end_hour=self.end_hour)
            ],
            penalty_linear_per_mwh=self.penalty_linear_per_mwh,
            confidence=1.0,
        )


class StartRequest(BaseModel):
    interval_seconds: float = 300.0
    obligations: list[ObligationIn] = Field(default_factory=list)


class OverrideRequest(BaseModel):
    asset_id: str
    mw: float
    reason: str


@router.post("/api/v1/dispatch/start")
async def dispatch_start(body: StartRequest | None = None) -> dict[str, Any]:
    """Start the dispatch scheduler against the currently active fleet."""
    global _scheduler
    fleet = get_fleet()
    if fleet is None:
        raise HTTPException(status_code=409, detail="No active fleet; start a fleet first.")

    if _scheduler is not None:
        await _scheduler.stop()

    scheduler = DispatchScheduler()
    interval = body.interval_seconds if body else 300.0
    obligations = [o.to_obligation() for o in body.obligations] if body else []
    await scheduler.start(
        fleet,
        HeuristicOptimizer(),
        price_feed=None,
        obligations=obligations,
        interval_seconds=interval,
    )
    _scheduler = scheduler
    return {"status": "started", "obligations": len(obligations)}


@router.post("/api/v1/dispatch/override")
async def dispatch_override(body: OverrideRequest) -> dict[str, str]:
    """Override the next dispatch decision for one asset (applied once)."""
    if _scheduler is None:
        raise HTTPException(status_code=409, detail="Dispatch scheduler not running.")
    _scheduler.set_override(body.asset_id, body.mw, body.reason)
    return {"status": "override_registered", "asset_id": body.asset_id}


@router.get("/api/v1/dispatch/current")
async def dispatch_current() -> dict[str, Any] | None:
    """Return the most recent dispatch plan, or null if none yet."""
    if _scheduler is None or _scheduler.last_plan is None:
        return None
    return asdict(_scheduler.last_plan)
