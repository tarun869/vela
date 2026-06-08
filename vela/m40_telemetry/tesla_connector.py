"""Tesla Gateway (Powerpack/Megapack) local-API connector.

Talks to the site-local Tesla Gateway REST API over HTTPS with a cookie session.

Dispatch limitation: the Gateway exposes only coarse operating-mode + backup
reserve controls, NOT a continuous MW setpoint like a full SCADA path. We map a
dispatch request onto ``operating_mode`` + ``backup_reserve_percent`` to bias
charge/discharge, but precise MW tracking is not guaranteed via this interface.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import httpx

from .base import AssetConnector
from .models import AssetTelemetry, IntegrationConfig
from .simulator import BESSSimulator

logger = logging.getLogger(__name__)


class TeslaGatewayConnector(AssetConnector):
    """Connects to a Tesla Gateway via its local REST API."""

    def __init__(
        self,
        config: IntegrationConfig,
        rated_mw: float,
        rated_mwh: float,
        tick_interval_seconds: float = 5.0,
        fallback_to_simulation: bool = True,
    ) -> None:
        super().__init__(config.asset_id, config)
        self.rated_mw = rated_mw
        self.rated_mwh = rated_mwh
        self.tick_interval_seconds = tick_interval_seconds
        self.fallback_to_simulation = fallback_to_simulation
        self._base_url = f"https://{config.host}" if config.host else ""
        self._client: httpx.AsyncClient | None = None
        self._fallback_sim: BESSSimulator | None = None

    def _activate_fallback(self, reason: str) -> bool:
        if not self.fallback_to_simulation:
            return False
        logger.warning("Tesla %s: falling back to simulation (%s)", self.asset_id, reason)
        self._fallback_sim = BESSSimulator(
            asset_id=self.asset_id,
            rated_mw=self.rated_mw,
            rated_mwh=self.rated_mwh,
            tick_interval_seconds=self.tick_interval_seconds,
        )
        return True

    async def connect(self) -> bool:
        email = self.config.extra_params.get("email", "")
        password = self.config.api_key or self.config.extra_params.get("password", "")
        try:
            client = httpx.AsyncClient(base_url=self._base_url, verify=False, timeout=10.0)
            resp = await client.post(
                "/api/login/Basic",
                json={"username": "customer", "email": email, "password": password},
            )
            resp.raise_for_status()
            self._client = client  # session cookie now stored on the client jar
            return True
        except Exception as exc:  # noqa: BLE001
            return self._activate_fallback(f"login failed: {exc}")

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _poll(self) -> AssetTelemetry:
        assert self._client is not None
        status = (await self._client.get("/api/system_status")).json()
        soe = (await self._client.get("/api/system_status/soe")).json()

        soc_pct = float(soe.get("percentage", status.get("soe", 0.0)))
        battery_power_w = float(status.get("battery_power", 0.0))
        nominal_full = float(status.get("nominal_full_pack_energy", 0.0)) or 1.0
        nominal_remaining = float(status.get("nominal_energy_remaining", nominal_full))
        # SoH proxy: degradation of usable pack energy vs nameplate.
        soh_pct = min(100.0, (nominal_full / (self.rated_mwh * 1_000_000.0)) * 100.0) or 100.0

        return AssetTelemetry(
            asset_id=self.asset_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            soc_pct=soc_pct,
            power_mw=battery_power_w / 1_000_000.0,
            temperature_c=float(status.get("temperature", 0.0)),
            voltage_v=750.0 + soc_pct * 2.5,
            soh_pct=soh_pct,
            alarm=None if nominal_remaining >= 0 else "PACK_FAULT",
            connection_status="connected",
        )

    async def send_dispatch(self, mw: float) -> bool:
        """Bias charge/discharge via operating mode + backup reserve (coarse).

        See module docstring: the Gateway has no continuous MW setpoint, so this
        only nudges behaviour and cannot precisely track ``mw``.
        """
        if self._fallback_sim is not None:
            return await self._fallback_sim.send_dispatch(mw)
        if self._client is None:
            return False
        # Discharge -> low reserve so the pack is allowed to export; charge -> high reserve.
        backup_reserve = 5 if mw > 0 else 95
        try:
            resp = await self._client.post(
                "/api/operation",
                json={"mode": "self_consumption", "backup_reserve_percent": backup_reserve},
            )
            resp.raise_for_status()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Tesla %s: dispatch failed: %s", self.asset_id, exc)
            return False

    async def stream(self) -> AsyncGenerator[AssetTelemetry, None]:
        if self._fallback_sim is not None:
            async for telemetry in self._fallback_sim.stream():
                self._mark_telemetry()
                yield telemetry
            return

        import asyncio

        while True:
            try:
                telemetry = await self._poll()
                self._mark_telemetry()
                yield telemetry
            except Exception as exc:  # noqa: BLE001
                if self._activate_fallback(f"poll failed: {exc}"):
                    sim = self._fallback_sim
                    assert sim is not None
                    async for telemetry in sim.stream():
                        self._mark_telemetry()
                        yield telemetry
                    return
            await asyncio.sleep(self.tick_interval_seconds)
