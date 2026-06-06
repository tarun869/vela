"""Dispatch endpoints: run optimization, get plan, approve/reject."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from vela.api.schemas import DispatchInterval

router = APIRouter()


class DispatchRequest(BaseModel):
    asset_ids: list[str] = Field(..., min_length=1, description="Assets to include in optimization")
    horizon_hours: int = Field(default=24, ge=1, le=168)
    market: str = Field(default="CAISO", description="Target market (CAISO, ERCOT, PJM, MISO)")
    lmp_override: list[float] | None = Field(default=None, description="Manual LMP forecast ($/MWh)")
    allow_ancillary: bool = True
    objective: Literal["revenue", "carbon", "balanced"] = "revenue"


class DispatchPlan(BaseModel):
    plan_id: str
    status: Literal["pending", "running", "complete", "failed", "approved", "rejected"]
    created_at: datetime
    asset_ids: list[str]
    horizon_hours: int
    market: str
    objective_value: float | None = None
    intervals: list[DispatchInterval] = Field(default_factory=list)
    solve_time_s: float | None = None
    message: str | None = None


class ApprovalRequest(BaseModel):
    action: Literal["approve", "reject"]
    comment: str | None = None


_PLANS: dict[str, DispatchPlan] = {}


@router.post("/run", response_model=DispatchPlan, status_code=202)
async def run_dispatch(
    request: DispatchRequest,
    background_tasks: BackgroundTasks,
) -> DispatchPlan:
    """
    Submit a dispatch optimization job. Returns immediately with a plan_id.
    Poll GET /v1/dispatch/plans/{plan_id} for results.
    """
    plan_id = str(uuid.uuid4())
    plan = DispatchPlan(
        plan_id=plan_id,
        status="pending",
        created_at=datetime.now(timezone.utc),
        asset_ids=request.asset_ids,
        horizon_hours=request.horizon_hours,
        market=request.market,
    )
    _PLANS[plan_id] = plan

    def _run_optimization(pid: str, req: DispatchRequest) -> None:
        import time
        from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer

        _PLANS[pid].status = "running"
        try:
            assets = [Asset(asset_id=aid, capacity_mwh=4.0, power_mw=2.0) for aid in req.asset_ids]
            lmp = req.lmp_override or [50.0] * req.horizon_hours
            optimizer = MILPDispatchOptimizer(horizon=req.horizon_hours)
            solution = optimizer.solve(assets=assets, lmp=lmp)
            now = datetime.now(timezone.utc)
            intervals: list[DispatchInterval] = []
            from datetime import timedelta
            for t in range(req.horizon_hours):
                for asset in assets:
                    intervals.append(DispatchInterval(
                        interval_start=now + timedelta(hours=t),
                        asset_id=asset.asset_id,
                        charge_mw=solution.charge_mw[asset.asset_id][t],
                        discharge_mw=solution.discharge_mw[asset.asset_id][t],
                        soc=solution.soc[asset.asset_id][t],
                        lmp=lmp[t],
                        revenue_usd=solution.discharge_mw[asset.asset_id][t] * lmp[t] * 1.0,
                    ))
            _PLANS[pid].status = "complete"
            _PLANS[pid].objective_value = solution.objective
            _PLANS[pid].intervals = intervals
            _PLANS[pid].solve_time_s = solution.solve_time_s
        except Exception as exc:
            _PLANS[pid].status = "failed"
            _PLANS[pid].message = str(exc)

    background_tasks.add_task(_run_optimization, plan_id, request)
    return plan


@router.get("/plans", response_model=list[DispatchPlan])
async def list_plans(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[DispatchPlan]:
    plans = list(_PLANS.values())
    if status:
        plans = [p for p in plans if p.status == status]
    return plans[-limit:]


@router.get("/plans/{plan_id}", response_model=DispatchPlan)
async def get_plan(plan_id: str) -> DispatchPlan:
    plan = _PLANS.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    return plan


@router.post("/plans/{plan_id}/approval", response_model=DispatchPlan)
async def approve_plan(plan_id: str, request: ApprovalRequest) -> DispatchPlan:
    plan = _PLANS.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    if plan.status not in ("complete",):
        raise HTTPException(
            status_code=409,
            detail=f"Plan must be 'complete' to approve/reject; current status: {plan.status}",
        )
    plan.status = "approved" if request.action == "approve" else "rejected"
    plan.message = request.comment
    return plan


@router.delete("/plans/{plan_id}", status_code=204)
async def delete_plan(plan_id: str) -> None:
    if plan_id not in _PLANS:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    del _PLANS[plan_id]
