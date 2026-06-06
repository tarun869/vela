"""Settlement endpoints: retrieve statements, trigger reconciliation."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class SettlementIntervalOut(BaseModel):
    interval_start: datetime
    scheduled_mwh: float
    metered_mwh: float
    lmp: float
    imbalance_mwh: float
    imbalance_charge_usd: float
    energy_revenue_usd: float
    net_revenue_usd: float


class SettlementStatementOut(BaseModel):
    statement_id: str
    asset_id: str
    market: str
    settlement_date: datetime
    status: Literal["pending", "preliminary", "final", "disputed"]
    total_energy_mwh: float
    total_revenue_usd: float
    total_imbalance_charge_usd: float
    net_revenue_usd: float
    intervals: list[SettlementIntervalOut] = Field(default_factory=list)


class ReconciliationRequest(BaseModel):
    asset_id: str
    market: str
    settlement_date: datetime
    scheduled_mwh: list[float] = Field(..., description="Hourly scheduled MWh (24 values)")
    metered_mwh: list[float] = Field(..., description="Hourly metered MWh (24 values)")
    lmp: list[float] = Field(..., description="Hourly LMP (24 values)")


_STATEMENTS: dict[str, SettlementStatementOut] = {}


@router.post("/reconcile", response_model=SettlementStatementOut, status_code=201)
async def reconcile(request: ReconciliationRequest) -> SettlementStatementOut:
    """Run settlement reconciliation for an asset for a given settlement date."""
    from vela.m9_settlement.settlement_engine import SettlementEngine, SettlementInterval
    from datetime import timedelta

    if len(request.scheduled_mwh) != len(request.metered_mwh) != len(request.lmp):
        raise HTTPException(status_code=422, detail="scheduled_mwh, metered_mwh, and lmp must have equal length")

    engine = SettlementEngine(market=request.market)
    statement = engine.calculate(
        asset_id=request.asset_id,
        settlement_date=request.settlement_date,
        scheduled_mwh=request.scheduled_mwh,
        metered_mwh=request.metered_mwh,
        lmp=request.lmp,
    )

    intervals_out: list[SettlementIntervalOut] = []
    for i, interval in enumerate(statement.intervals):
        imbalance = interval.metered_mwh - interval.scheduled_mwh
        intervals_out.append(SettlementIntervalOut(
            interval_start=interval.interval_start,
            scheduled_mwh=interval.scheduled_mwh,
            metered_mwh=interval.metered_mwh,
            lmp=interval.lmp,
            imbalance_mwh=round(imbalance, 4),
            imbalance_charge_usd=round(interval.imbalance_charge, 4),
            energy_revenue_usd=round(interval.metered_mwh * interval.lmp, 4),
            net_revenue_usd=round(interval.revenue, 4),
        ))

    stmt_id = str(uuid.uuid4())
    stmt = SettlementStatementOut(
        statement_id=stmt_id,
        asset_id=statement.asset_id,
        market=statement.market,
        settlement_date=statement.settlement_date,
        status="preliminary",
        total_energy_mwh=round(statement.total_energy_mwh, 4),
        total_revenue_usd=round(statement.total_revenue, 4),
        total_imbalance_charge_usd=round(statement.total_imbalance_charge, 4),
        net_revenue_usd=round(statement.total_revenue - statement.total_imbalance_charge, 4),
        intervals=intervals_out,
    )
    _STATEMENTS[stmt_id] = stmt
    return stmt


@router.get("/statements", response_model=list[SettlementStatementOut])
async def list_statements(
    asset_id: str | None = Query(default=None),
    market: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
) -> list[SettlementStatementOut]:
    stmts = list(_STATEMENTS.values())
    if asset_id:
        stmts = [s for s in stmts if s.asset_id == asset_id]
    if market:
        stmts = [s for s in stmts if s.market == market]
    if status:
        stmts = [s for s in stmts if s.status == status]
    return stmts[-limit:]


@router.get("/statements/{statement_id}", response_model=SettlementStatementOut)
async def get_statement(statement_id: str) -> SettlementStatementOut:
    stmt = _STATEMENTS.get(statement_id)
    if not stmt:
        raise HTTPException(status_code=404, detail=f"Statement {statement_id} not found")
    return stmt


@router.post("/statements/{statement_id}/finalize", response_model=SettlementStatementOut)
async def finalize_statement(statement_id: str) -> SettlementStatementOut:
    stmt = _STATEMENTS.get(statement_id)
    if not stmt:
        raise HTTPException(status_code=404, detail=f"Statement {statement_id} not found")
    stmt.status = "final"
    return stmt
