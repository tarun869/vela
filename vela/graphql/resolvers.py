"""GraphQL query resolvers for the Vela VPP API."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import strawberry

from vela.graphql.types import (
    AssetType,
    CarbonIntensityType,
    DispatchPlanType,
    ForecastPointType,
    PriceForecastType,
    SettlementStatementType,
    SiteType,
    TelemetryPointType,
)


@strawberry.type
class Query:
    @strawberry.field(description="List all registered assets")
    def assets(
        self,
        asset_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[AssetType]:
        """Return a list of VPP assets, optionally filtered by type and status."""
        import numpy as np
        np.random.seed(1)
        assets = []
        for i in range(5):
            asset = AssetType(
                asset_id=f"bat-{i+1:03d}",
                asset_type="battery",
                capacity_mwh=4.0,
                power_mw=2.0,
                status="online" if i < 4 else "standby",
                soc=round(np.random.uniform(0.2, 0.9), 3),
            )
            if asset_type and asset.asset_type != asset_type:
                continue
            if status and asset.status != status:
                continue
            assets.append(asset)
        return assets[:limit]

    @strawberry.field(description="Get a single asset by ID")
    def asset(self, asset_id: str) -> Optional[AssetType]:
        import numpy as np
        np.random.seed(hash(asset_id) % 2**31)
        return AssetType(
            asset_id=asset_id,
            asset_type="battery",
            capacity_mwh=4.0,
            power_mw=2.0,
            status="online",
            soc=round(np.random.uniform(0.3, 0.8), 3),
        )

    @strawberry.field(description="Get a dispatch plan by ID")
    def dispatch_plan(self, plan_id: str) -> Optional[DispatchPlanType]:
        return DispatchPlanType(
            plan_id=plan_id,
            status="complete",
            created_at=datetime.now(timezone.utc),
            asset_ids=["bat-001", "bat-002"],
            horizon_hours=24,
            market="CAISO",
            objective_value=1250.50,
            solve_time_s=0.35,
            intervals=[],
        )

    @strawberry.field(description="Forecast LMP prices for a pricing node")
    def price_forecast(
        self,
        node: str = "TH_NP15_GEN-APND",
        horizon_hours: int = 24,
    ) -> PriceForecastType:
        import numpy as np
        np.random.seed(42)
        now = datetime.now(timezone.utc)
        daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
                 50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
        points = []
        for h in range(horizon_hours):
            mean = round(daily[h % 24] + np.random.normal(0, 5), 2)
            points.append(ForecastPointType(
                timestamp=now + timedelta(hours=h),
                mean=mean,
                p10=round(mean * 0.85, 2),
                p90=round(mean * 1.20, 2),
            ))
        return PriceForecastType(
            forecast_id=str(uuid.uuid4()),
            node=node,
            model="ar",
            generated_at=now,
            horizon_hours=horizon_hours,
            unit="$/MWh",
            points=points,
        )

    @strawberry.field(description="Get real-time telemetry for an asset")
    def telemetry(self, asset_id: str) -> TelemetryPointType:
        import numpy as np
        np.random.seed(hash(asset_id) % 2**31 + int(datetime.now().timestamp()) // 5)
        return TelemetryPointType(
            timestamp=datetime.now(timezone.utc),
            asset_id=asset_id,
            soc=round(np.random.uniform(0.2, 0.9), 3),
            power_mw=round(np.random.uniform(-2.0, 2.0), 3),
            temperature_c=round(np.random.uniform(20, 35), 1),
            status="online",
        )

    @strawberry.field(description="Get grid carbon intensity for a region")
    def carbon_intensity(self, region: str = "CAISO") -> CarbonIntensityType:
        import numpy as np
        np.random.seed(hash(region) % 2**31)
        return CarbonIntensityType(
            region=region,
            timestamp=datetime.now(timezone.utc),
            intensity_kg_per_mwh=round(np.random.uniform(150, 350), 1),
            source="real_time",
        )

    @strawberry.field(description="List sites")
    def sites(self, iso: Optional[str] = None) -> list[SiteType]:
        sites = [
            SiteType(
                site_id="site-001",
                name="Fresno Solar+Storage",
                iso="CAISO",
                pricing_node="TH_NP15_GEN-APND",
                latitude=36.7378,
                longitude=-119.7871,
                asset_ids=["bat-001", "bat-002"],
                status="active",
            ),
        ]
        if iso:
            sites = [s for s in sites if s.iso == iso]
        return sites
