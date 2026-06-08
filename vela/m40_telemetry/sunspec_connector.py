"""SunSpec-over-Modbus-TCP connector for SunSpec-compliant battery systems.

Reads SunSpec Model 124 (storage) and Model 802 (battery) registers via
``pymodbus``. ``pymodbus`` is imported lazily so this module imports cleanly even
where the dependency is absent (e.g. CI without hardware extras).

For demos, ``fallback_to_simulation`` transparently swaps in a
:class:`~vela.m40_telemetry.simulator.BESSSimulator` if the Modbus connection
cannot be established or repeatedly fails.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

from .base import AssetConnector
from .models import AssetTelemetry, IntegrationConfig
from .simulator import BESSSimulator

logger = logging.getLogger(__name__)

# Standard SunSpec register map (Model 124 storage + Model 802 battery).
REG_SOC = 40070  # SoC (scaled %)
REG_W = 40075  # Active power W (also WMaxRte setpoint target)
REG_WH = 40077  # Energy Wh
REG_TMP_AMB = 40082  # Ambient temperature
REG_ALM_INFO = 40093  # Alarm bitfield

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0


class SunSpecModbusConnector(AssetConnector):
    """Connects to any SunSpec-compliant battery via Modbus TCP."""

    def __init__(
        self,
        config: IntegrationConfig,
        rated_mw: float,
        rated_mwh: float,
        chemistry: str = "LFP",
        tick_interval_seconds: float = 5.0,
        fallback_to_simulation: bool = True,
    ) -> None:
        super().__init__(config.asset_id, config)
        self.rated_mw = rated_mw
        self.rated_mwh = rated_mwh
        self.chemistry = chemistry
        self.tick_interval_seconds = tick_interval_seconds
        self.fallback_to_simulation = fallback_to_simulation
        self._client: Any | None = None
        self._fallback_sim: BESSSimulator | None = None

    def _activate_fallback(self, reason: str) -> bool:
        if not self.fallback_to_simulation:
            return False
        logger.warning("SunSpec %s: falling back to simulation (%s)", self.asset_id, reason)
        self._fallback_sim = BESSSimulator(
            asset_id=self.asset_id,
            rated_mw=self.rated_mw,
            rated_mwh=self.rated_mwh,
            chemistry=self.chemistry,
            tick_interval_seconds=self.tick_interval_seconds,
        )
        return True

    async def connect(self) -> bool:
        try:
            from pymodbus.client import AsyncModbusTcpClient  # type: ignore[import-not-found]
        except ImportError:
            return self._activate_fallback("pymodbus not installed")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                client = AsyncModbusTcpClient(self.config.host, port=self.config.port or 502)
                connected = await client.connect()
                if connected:
                    self._client = client
                    return True
                logger.warning(
                    "SunSpec %s: connect attempt %d/%d failed", self.asset_id, attempt, MAX_RETRIES
                )
            except Exception as exc:  # noqa: BLE001 - retry on any transport error
                logger.warning("SunSpec %s: connect error %s", self.asset_id, exc)
            await asyncio.sleep(RETRY_BACKOFF_SECONDS)

        return self._activate_fallback("connection failed after retries")

    async def disconnect(self) -> None:
        if self._client is not None:
            close = self._client.close()
            if asyncio.iscoroutine(close):
                await close
            self._client = None

    async def _read_registers(self) -> AssetTelemetry:
        """Read one telemetry sample from the live device (raises on failure)."""
        assert self._client is not None
        soc = await self._client.read_holding_registers(REG_SOC, count=1)
        power = await self._client.read_holding_registers(REG_W, count=1)
        temp = await self._client.read_holding_registers(REG_TMP_AMB, count=1)
        alarm_bits = await self._client.read_holding_registers(REG_ALM_INFO, count=1)

        soc_pct = float(soc.registers[0]) / 100.0
        power_w = float(power.registers[0])
        alarm = "DEVICE_ALARM" if alarm_bits.registers[0] != 0 else None
        return AssetTelemetry(
            asset_id=self.asset_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            soc_pct=soc_pct,
            power_mw=power_w / 1_000_000.0,
            temperature_c=float(temp.registers[0]) / 10.0,
            voltage_v=750.0 + soc_pct * 2.5,
            soh_pct=100.0,
            alarm=alarm,
            connection_status="connected",
        )

    async def send_dispatch(self, mw: float) -> bool:
        if self._fallback_sim is not None:
            return await self._fallback_sim.send_dispatch(mw)
        if self._client is None:
            return False
        try:
            watts = int(_clamp(mw, -self.rated_mw, self.rated_mw) * 1_000_000)
            await self._client.write_register(REG_W, watts)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("SunSpec %s: dispatch write failed: %s", self.asset_id, exc)
            return False

    async def stream(self) -> AsyncGenerator[AssetTelemetry, None]:
        if self._fallback_sim is not None:
            async for telemetry in self._fallback_sim.stream():
                self._mark_telemetry()
                yield telemetry
            return

        consecutive_failures = 0
        while True:
            try:
                telemetry = await self._read_registers()
                consecutive_failures = 0
                self._mark_telemetry()
                yield telemetry
            except Exception as exc:  # noqa: BLE001
                consecutive_failures += 1
                logger.warning(
                    "SunSpec %s: read failed %d/%d: %s",
                    self.asset_id,
                    consecutive_failures,
                    MAX_RETRIES,
                    exc,
                )
                if consecutive_failures >= MAX_RETRIES:
                    if self._activate_fallback("repeated read failures"):
                        sim = self._fallback_sim
                        assert sim is not None
                        async for telemetry in sim.stream():
                            self._mark_telemetry()
                            yield telemetry
                        return
                    yield self._error_telemetry()
                    consecutive_failures = 0
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
            await asyncio.sleep(self.tick_interval_seconds)

    def _error_telemetry(self) -> AssetTelemetry:
        return AssetTelemetry(
            asset_id=self.asset_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            soc_pct=0.0,
            power_mw=0.0,
            temperature_c=0.0,
            voltage_v=0.0,
            soh_pct=0.0,
            alarm="CONNECTION_ERROR",
            connection_status="error",
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
