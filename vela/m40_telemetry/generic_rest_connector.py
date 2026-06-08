"""Generic REST connector for assets exposing HTTP telemetry endpoints.

Covers Fluence Nispera, custom BEMS REST APIs, etc. All endpoint URLs, auth, and
JSON field locations are supplied via ``IntegrationConfig.extra_params`` so a new
vendor can be onboarded with config alone.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import AssetConnector
from .models import AssetTelemetry, IntegrationConfig

logger = logging.getLogger(__name__)


def resolve_path(payload: Any, dotted: str) -> Any:
    """Resolve a dot-notation path (e.g. ``data.battery.soc``) within nested JSON."""
    current = payload
    for part in dotted.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class GenericRESTConnector(AssetConnector):
    """Config-driven REST telemetry/dispatch connector."""

    def __init__(
        self,
        config: IntegrationConfig,
        tick_interval_seconds: float | None = None,
    ) -> None:
        super().__init__(config.asset_id, config)
        params = config.extra_params
        self.telemetry_endpoint: str = params.get("telemetry_endpoint", "")
        self.dispatch_endpoint: str = params.get("dispatch_endpoint", "")
        self.auth_type: str = params.get("auth_type", "bearer")
        self.auth_header: str = params.get("auth_header", "X-API-Key")
        self.soc_field: str = params.get("soc_field", "soc")
        self.power_field: str = params.get("power_field", "power")
        self.temperature_field: str = params.get("temperature_field", "temperature")
        self.soh_field: str = params.get("soh_field", "soh")
        self.poll_interval = (
            tick_interval_seconds
            if tick_interval_seconds is not None
            else float(params.get("poll_interval", 5))
        )
        self._client: httpx.AsyncClient | None = None

    def _auth(self) -> dict[str, str]:
        key = self.config.api_key or ""
        if not key:
            return {}
        if self.auth_type == "bearer":
            return {"Authorization": f"Bearer {key}"}
        if self.auth_type == "api_key_header":
            return {self.auth_header: key}
        if self.auth_type == "basic":
            return {"Authorization": f"Basic {key}"}
        return {}

    def _url(self, template: str) -> str:
        return template.replace("{asset_id}", self.asset_id)

    async def connect(self) -> bool:
        self._client = httpx.AsyncClient(headers=self._auth(), timeout=10.0)
        return True

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _poll(self) -> AssetTelemetry:
        assert self._client is not None
        resp = await self._client.get(self._url(self.telemetry_endpoint))
        resp.raise_for_status()
        payload = resp.json()

        soc = float(resolve_path(payload, self.soc_field) or 0.0)
        power = float(resolve_path(payload, self.power_field) or 0.0)
        temp = resolve_path(payload, self.temperature_field)
        soh = resolve_path(payload, self.soh_field)
        return AssetTelemetry(
            asset_id=self.asset_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            soc_pct=soc,
            power_mw=power,
            temperature_c=float(temp) if temp is not None else 0.0,
            voltage_v=750.0 + soc * 2.5,
            soh_pct=float(soh) if soh is not None else 100.0,
            alarm=None,
            connection_status="connected",
        )

    async def send_dispatch(self, mw: float) -> bool:
        if self._client is None or not self.dispatch_endpoint:
            return False
        try:
            resp = await self._client.post(
                self._url(self.dispatch_endpoint),
                json={"asset_id": self.asset_id, "setpoint_mw": mw},
            )
            resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("GenericREST %s: dispatch failed: %s", self.asset_id, exc)
            return False

    async def stream(self) -> AsyncGenerator[AssetTelemetry, None]:
        while True:
            try:
                telemetry = await self._poll()
                self._mark_telemetry()
                yield telemetry
            except Exception as exc:  # noqa: BLE001
                logger.warning("GenericREST %s: poll failed: %s", self.asset_id, exc)
            await asyncio.sleep(self.poll_interval)
