"""GraphQL mutations for the Vela VPP API."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import strawberry

from vela.graphql.types import AssetInput, AssetType, DispatchInput, DispatchPlanType


@strawberry.type
class Mutation:
    @strawberry.mutation(description="Register a new asset")
    def create_asset(self, input: AssetInput) -> AssetType:
        return AssetType(
            asset_id=str(uuid.uuid4()),
            asset_type=input.asset_type,
            capacity_mwh=input.capacity_mwh,
            power_mw=input.power_mw,
            status=input.status,
            soc=input.soc,
        )

    @strawberry.mutation(description="Update asset state of charge")
    def update_soc(self, asset_id: str, soc: float) -> AssetType:
        if not (0.0 <= soc <= 1.0):
            raise ValueError(f"SOC must be between 0.0 and 1.0, got {soc}")
        return AssetType(
            asset_id=asset_id,
            asset_type="battery",
            capacity_mwh=4.0,
            power_mw=2.0,
            status="online",
            soc=round(soc, 4),
        )

    @strawberry.mutation(description="Submit a dispatch optimization request")
    def submit_dispatch(self, input: DispatchInput) -> DispatchPlanType:
        return DispatchPlanType(
            plan_id=str(uuid.uuid4()),
            status="pending",
            created_at=datetime.now(timezone.utc),
            asset_ids=input.asset_ids,
            horizon_hours=input.horizon_hours,
            market=input.market,
            objective_value=None,
            solve_time_s=None,
            intervals=[],
        )

    @strawberry.mutation(description="Approve a dispatch plan for execution")
    def approve_dispatch_plan(self, plan_id: str) -> DispatchPlanType:
        return DispatchPlanType(
            plan_id=plan_id,
            status="approved",
            created_at=datetime.now(timezone.utc),
            asset_ids=[],
            horizon_hours=24,
            market="CAISO",
            objective_value=None,
            solve_time_s=None,
            intervals=[],
        )

    @strawberry.mutation(description="Reject a dispatch plan")
    def reject_dispatch_plan(self, plan_id: str, reason: str = "") -> DispatchPlanType:
        return DispatchPlanType(
            plan_id=plan_id,
            status="rejected",
            created_at=datetime.now(timezone.utc),
            asset_ids=[],
            horizon_hours=24,
            market="CAISO",
            objective_value=None,
            solve_time_s=None,
            intervals=[],
        )

    @strawberry.mutation(description="Deactivate an asset")
    def deactivate_asset(self, asset_id: str, reason: str = "") -> AssetType:
        return AssetType(
            asset_id=asset_id,
            asset_type="battery",
            capacity_mwh=4.0,
            power_mw=2.0,
            status="offline",
            soc=None,
        )
