"""Site management endpoints: physical site registration and metadata."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class SiteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    utility_account: str | None = None
    utility_name: str | None = None
    iso: Literal["CAISO", "ERCOT", "PJM", "MISO", "SPP", "NYISO", "ISONE"] = "CAISO"
    pricing_node: str | None = None
    meter_id: str | None = None
    timezone: str = "America/Los_Angeles"


class Site(BaseModel):
    site_id: str
    name: str
    address: str | None
    latitude: float | None
    longitude: float | None
    utility_account: str | None
    utility_name: str | None
    iso: str
    pricing_node: str | None
    meter_id: str | None
    timezone: str
    asset_ids: list[str] = Field(default_factory=list)
    status: Literal["active", "inactive", "commissioning", "decommissioned"] = "active"
    created_at: datetime
    commissioned_at: datetime | None = None


class SiteStats(BaseModel):
    site_id: str
    total_capacity_mwh: float
    total_power_mw: float
    asset_count: int
    online_count: int
    avg_soc: float
    last_dispatch: datetime | None = None


_SITES: dict[str, Site] = {}


@router.post("/", response_model=Site, status_code=201)
async def create_site(request: SiteCreate) -> Site:
    site = Site(
        site_id=str(uuid.uuid4()),
        name=request.name,
        address=request.address,
        latitude=request.latitude,
        longitude=request.longitude,
        utility_account=request.utility_account,
        utility_name=request.utility_name,
        iso=request.iso,
        pricing_node=request.pricing_node,
        meter_id=request.meter_id,
        timezone=request.timezone,
        created_at=datetime.now(timezone.utc),
    )
    _SITES[site.site_id] = site
    return site


@router.get("/", response_model=list[Site])
async def list_sites(
    iso: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[Site]:
    sites = list(_SITES.values())
    if iso:
        sites = [s for s in sites if s.iso == iso]
    if status:
        sites = [s for s in sites if s.status == status]
    return sites[:limit]


@router.get("/{site_id}", response_model=Site)
async def get_site(site_id: str) -> Site:
    site = _SITES.get(site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")
    return site


@router.put("/{site_id}", response_model=Site)
async def update_site(site_id: str, request: SiteCreate) -> Site:
    site = _SITES.get(site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(site, field, value)
    return site


@router.delete("/{site_id}", status_code=204)
async def delete_site(site_id: str) -> None:
    if site_id not in _SITES:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")
    del _SITES[site_id]


@router.get("/{site_id}/stats", response_model=SiteStats)
async def get_site_stats(site_id: str) -> SiteStats:
    site = _SITES.get(site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")
    import numpy as np
    n = len(site.asset_ids)
    return SiteStats(
        site_id=site_id,
        total_capacity_mwh=n * 4.0,
        total_power_mw=n * 2.0,
        asset_count=n,
        online_count=max(0, n - 1) if n > 0 else 0,
        avg_soc=round(np.random.uniform(0.4, 0.8), 3),
        last_dispatch=datetime.now(timezone.utc) if n > 0 else None,
    )


@router.patch("/{site_id}/assets", response_model=Site)
async def assign_assets(
    site_id: str,
    add: list[str] = Query(default=[]),
    remove: list[str] = Query(default=[]),
) -> Site:
    site = _SITES.get(site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")
    asset_set = set(site.asset_ids)
    asset_set.update(add)
    asset_set -= set(remove)
    site.asset_ids = sorted(asset_set)
    return site
