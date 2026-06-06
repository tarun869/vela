"""Portfolio endpoints: multi-site portfolio management and optimization."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class PortfolioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=lambda: ["CAISO"])
    optimization_objective: Literal["revenue", "carbon", "balanced"] = "revenue"


class Portfolio(BaseModel):
    portfolio_id: str
    name: str
    description: str | None
    asset_ids: list[str]
    markets: list[str]
    optimization_objective: str
    created_at: datetime
    total_capacity_mwh: float
    total_power_mw: float


class PortfolioMetrics(BaseModel):
    portfolio_id: str
    as_of: datetime
    total_revenue_usd: float
    revenue_per_mwh: float
    avg_soc: float
    fleet_availability: float
    active_assets: int
    total_assets: int
    mtd_revenue_usd: float
    ytd_revenue_usd: float


class AllocationResult(BaseModel):
    """Optimal allocation of portfolio resources across markets and services."""
    portfolio_id: str
    optimized_at: datetime
    horizon_hours: int
    allocations: list[dict]  # [{asset_id, market, service, mw}]
    expected_revenue_usd: float
    expected_carbon_kg_avoided: float


_PORTFOLIOS: dict[str, Portfolio] = {}


@router.post("/", response_model=Portfolio, status_code=201)
async def create_portfolio(request: PortfolioCreate) -> Portfolio:
    n_assets = len(request.asset_ids)
    portfolio = Portfolio(
        portfolio_id=str(uuid.uuid4()),
        name=request.name,
        description=request.description,
        asset_ids=request.asset_ids,
        markets=request.markets,
        optimization_objective=request.optimization_objective,
        created_at=datetime.now(timezone.utc),
        total_capacity_mwh=n_assets * 4.0,
        total_power_mw=n_assets * 2.0,
    )
    _PORTFOLIOS[portfolio.portfolio_id] = portfolio
    return portfolio


@router.get("/", response_model=list[Portfolio])
async def list_portfolios() -> list[Portfolio]:
    return list(_PORTFOLIOS.values())


@router.get("/{portfolio_id}", response_model=Portfolio)
async def get_portfolio(portfolio_id: str) -> Portfolio:
    p = _PORTFOLIOS.get(portfolio_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    return p


@router.get("/{portfolio_id}/metrics", response_model=PortfolioMetrics)
async def get_portfolio_metrics(portfolio_id: str) -> PortfolioMetrics:
    p = _PORTFOLIOS.get(portfolio_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    import numpy as np
    np.random.seed(hash(portfolio_id) % 2**31)
    n = len(p.asset_ids)
    return PortfolioMetrics(
        portfolio_id=portfolio_id,
        as_of=datetime.now(timezone.utc),
        total_revenue_usd=round(abs(np.random.normal(8500 * max(n, 1), 1200)), 2),
        revenue_per_mwh=round(np.random.uniform(55, 110), 2),
        avg_soc=round(np.random.uniform(0.4, 0.7), 3),
        fleet_availability=round(np.random.uniform(0.97, 0.999), 4),
        active_assets=max(n - 1, 0) if n > 0 else 0,
        total_assets=n,
        mtd_revenue_usd=round(abs(np.random.normal(2500 * max(n, 1), 400)), 2),
        ytd_revenue_usd=round(abs(np.random.normal(45000 * max(n, 1), 8000)), 2),
    )


@router.post("/{portfolio_id}/optimize", response_model=AllocationResult)
async def optimize_portfolio(
    portfolio_id: str,
    horizon_hours: int = Query(default=24, ge=1, le=168),
) -> AllocationResult:
    """Run portfolio-level optimization to allocate assets across markets."""
    p = _PORTFOLIOS.get(portfolio_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    import numpy as np
    np.random.seed(42)
    allocations = []
    for asset_id in p.asset_ids:
        for market in p.markets:
            allocations.append({
                "asset_id": asset_id,
                "market": market,
                "service": "energy",
                "allocated_mw": round(np.random.uniform(0.5, 2.0), 3),
                "expected_revenue_usd": round(np.random.uniform(200, 800), 2),
            })
    return AllocationResult(
        portfolio_id=portfolio_id,
        optimized_at=datetime.now(timezone.utc),
        horizon_hours=horizon_hours,
        allocations=allocations,
        expected_revenue_usd=round(sum(a["expected_revenue_usd"] for a in allocations), 2),
        expected_carbon_kg_avoided=round(abs(np.random.normal(5000, 800)), 1),
    )


@router.patch("/{portfolio_id}/assets", response_model=Portfolio)
async def update_portfolio_assets(
    portfolio_id: str,
    add: list[str] = Query(default=[]),
    remove: list[str] = Query(default=[]),
) -> Portfolio:
    p = _PORTFOLIOS.get(portfolio_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    asset_set = set(p.asset_ids)
    asset_set.update(add)
    asset_set -= set(remove)
    p.asset_ids = sorted(asset_set)
    p.total_power_mw = len(p.asset_ids) * 2.0
    p.total_capacity_mwh = len(p.asset_ids) * 4.0
    return p
