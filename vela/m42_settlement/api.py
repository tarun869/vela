"""FastAPI router for settlement and performance tracking."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

from .tracker import SettlementTracker

router = APIRouter()

_tracker: SettlementTracker | None = None


def get_tracker() -> SettlementTracker | None:
    return _tracker


def set_tracker(tracker: SettlementTracker | None) -> None:
    """Test/seam hook to inject or reset the active tracker."""
    global _tracker
    _tracker = tracker


@router.get("/api/v1/settlement/summary")
async def settlement_summary() -> dict[str, Any]:
    """Return the current P&L summary (can be called mid-day or end of day)."""
    if _tracker is None:
        raise HTTPException(status_code=409, detail="No active settlement tracker.")
    return asdict(_tracker.generate_summary())


@router.get("/api/v1/settlement/records")
async def settlement_records() -> list[dict[str, Any]]:
    """Return every dispatch record accumulated so far (detailed timeline)."""
    if _tracker is None:
        raise HTTPException(status_code=409, detail="No active settlement tracker.")
    return [asdict(r) for r in _tracker.dispatch_records]
