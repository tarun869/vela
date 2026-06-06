"""GraphQL subscriptions for real-time data streaming."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import AsyncGenerator

import strawberry

from vela.graphql.types import TelemetryPointType, DispatchIntervalType, CarbonIntensityType


@strawberry.type
class Subscription:
    @strawberry.subscription(description="Stream real-time telemetry for an asset")
    async def telemetry_stream(
        self,
        asset_id: str,
        interval_seconds: float = 1.0,
    ) -> AsyncGenerator[TelemetryPointType, None]:
        """Emit a telemetry reading every `interval_seconds` for the given asset."""
        soc = random.uniform(0.3, 0.8)
        while True:
            soc = max(0.05, min(0.95, soc + random.uniform(-0.02, 0.02)))
            yield TelemetryPointType(
                timestamp=datetime.now(timezone.utc),
                asset_id=asset_id,
                soc=round(soc, 4),
                power_mw=round(random.uniform(-2.0, 2.0), 3),
                temperature_c=round(random.uniform(20.0, 35.0), 1),
                status="online",
            )
            await asyncio.sleep(interval_seconds)

    @strawberry.subscription(description="Stream carbon intensity updates for a region")
    async def carbon_intensity_stream(
        self,
        region: str = "CAISO",
        interval_seconds: float = 60.0,
    ) -> AsyncGenerator[CarbonIntensityType, None]:
        """Emit carbon intensity updates for a region."""
        base = 220.0
        while True:
            intensity = max(50.0, base + random.normalvariate(0, 30))
            yield CarbonIntensityType(
                region=region,
                timestamp=datetime.now(timezone.utc),
                intensity_kg_per_mwh=round(intensity, 1),
                source="real_time",
            )
            await asyncio.sleep(interval_seconds)

    @strawberry.subscription(description="Stream dispatch interval updates")
    async def dispatch_updates(
        self,
        asset_id: str,
    ) -> AsyncGenerator[DispatchIntervalType, None]:
        """Emit dispatch updates as new optimization results are published."""
        soc = 0.5
        lmp = 55.0
        while True:
            soc = max(0.05, min(0.95, soc + random.uniform(-0.05, 0.05)))
            lmp = max(10.0, lmp + random.normalvariate(0, 8))
            discharge = random.uniform(0.0, 2.0)
            charge = 0.0 if discharge > 0 else random.uniform(0.0, 2.0)
            yield DispatchIntervalType(
                interval_start=datetime.now(timezone.utc),
                asset_id=asset_id,
                charge_mw=round(charge, 3),
                discharge_mw=round(discharge, 3),
                soc=round(soc, 4),
                lmp=round(lmp, 2),
                revenue_usd=round(discharge * lmp * (5 / 60), 4),  # 5-minute interval
            )
            await asyncio.sleep(5.0)
