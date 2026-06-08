"""FastAPI router + WebSocket for live fleet telemetry."""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from vela.m39_extraction.models import ExtractedAsset

from .fleet_manager import FleetManager
from .models import IntegrationConfig, Protocol

logger = logging.getLogger(__name__)

router = APIRouter()

# Process-wide active fleet. Started via /connect or /demo.
_fleet: FleetManager | None = None


def get_fleet() -> FleetManager | None:
    return _fleet


def set_fleet(fleet: FleetManager | None) -> None:
    """Test/seam hook to inject a pre-built fleet."""
    global _fleet
    _fleet = fleet


class IntegrationConfigIn(BaseModel):
    asset_id: str
    protocol: Protocol
    host: str | None = None
    port: int | None = None
    api_key: str | None = None
    extra_params: dict[str, Any] = Field(default_factory=dict)
    simulate: bool = False

    def to_dataclass(self) -> IntegrationConfig:
        return IntegrationConfig(**self.model_dump())


class DemoAssetIn(BaseModel):
    asset_id: str
    asset_type: Literal["BESS", "Solar", "Wind", "EV_Fleet", "Flex_Load"] = "BESS"
    rated_mw: float = 10.0
    rated_mwh: float | None = None
    chemistry: Literal["LFP", "NMC", "NCA"] | None = None

    def to_extracted_asset(self) -> ExtractedAsset:
        return ExtractedAsset(
            asset_id=self.asset_id,
            asset_type=self.asset_type,
            rated_mw=self.rated_mw,
            rated_mwh=self.rated_mwh,
            chemistry=self.chemistry,
            confidence=1.0,
        )


@router.get("/api/v1/fleet/state")
async def fleet_state() -> dict[str, Any]:
    """Current telemetry snapshot for all assets."""
    if _fleet is None:
        return {"assets": {}, "price": None}
    return await _fleet.get_fleet_state()


@router.post("/api/v1/fleet/connect")
async def fleet_connect(configs: list[IntegrationConfigIn]) -> dict[str, str]:
    """Start the fleet with the given configs; returns per-asset connection mode."""
    global _fleet
    fleet = FleetManager([c.to_dataclass() for c in configs])
    await fleet.start()
    _fleet = fleet
    return {
        cfg.asset_id: (
            "simulated" if (cfg.simulate or cfg.protocol == "simulated") else cfg.protocol
        )
        for cfg in configs
    }


@router.post("/api/v1/fleet/demo")
async def fleet_demo(assets: list[DemoAssetIn]) -> dict[str, Any]:
    """Spin up an all-simulated demo fleet; returns immediately (streams in background)."""
    global _fleet
    fleet = FleetManager.from_demo_fleet([a.to_extracted_asset() for a in assets])
    await fleet.start()
    _fleet = fleet
    return {"status": "started", "assets": list(fleet.connectors.keys())}


@router.websocket("/ws/fleet/telemetry")
async def fleet_telemetry_ws(websocket: WebSocket) -> None:
    """Stream AssetTelemetry and PriceTick messages as JSON to the client."""
    await websocket.accept()
    fleet = _fleet
    if fleet is None:
        await websocket.send_json({"type": "error", "data": {"message": "no active fleet"}})
        await websocket.close()
        return

    queue = fleet.subscribe()
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        fleet.unsubscribe(queue)
