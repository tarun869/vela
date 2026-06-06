"""Asset management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class AssetResponse(BaseModel):
    asset_id: str
    asset_type: str
    capacity_mwh: float | None
    power_mw: float
    status: str
    soc: float | None


@router.get("/", response_model=list[AssetResponse])
async def list_assets() -> list[AssetResponse]:
    return []


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(asset_id: str) -> AssetResponse:
    raise HTTPException(status_code=404, detail="Asset not found")


@router.post("/", response_model=AssetResponse, status_code=201)
async def create_asset(payload: AssetResponse) -> AssetResponse:
    return payload
