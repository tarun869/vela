"""Realistic, fully-async telemetry simulators (BESS + Solar).

These are the default connectors in demo mode and the fallback for real
integrations that fail to connect. They implement the same
:class:`~vela.m40_telemetry.base.AssetConnector` interface as the hardware
connectors, so they are drop-in interchangeable.
"""
from __future__ import annotations

import asyncio
import math
import random
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone

from .base import AssetConnector
from .models import AssetTelemetry, IntegrationConfig

Clock = Callable[[], datetime]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BESSSimulator(AssetConnector):
    """Realistic battery energy storage telemetry simulator.

    SOC dynamics:  dSOC/dt = -(P_net / E_rated) * (dt / 3600)
    Temperature:   T_ambient + |P| * 0.9 + gaussian noise,
                   T_ambient = 25 + 8 * sin(2*pi*hour/24)  (diurnal)
    SOH:           degrades with cumulative throughput; rate by chemistry
                   (LFP 1%/1500 MWh, NMC 1%/800 MWh, NCA 1%/600 MWh)
    Voltage:       750 + SOC * 250
    SOC clamps to [5%, 98%]; power clamps to +/- rated_mw.

    ``real_time=False`` integrates one ``tick_interval_seconds`` of physics per
    tick without sleeping — useful for fast, deterministic tests.
    """

    # MWh of throughput that degrades SOH by 1%, per chemistry.
    _DEGRADATION_MWH_PER_PCT: dict[str, float] = {
        "LFP": 1500.0,
        "NMC": 800.0,
        "NCA": 600.0,
    }

    def __init__(
        self,
        asset_id: str,
        rated_mw: float,
        rated_mwh: float,
        initial_soc: float = 0.65,
        initial_soh: float = 0.94,
        chemistry: str = "LFP",
        tick_interval_seconds: float = 5.0,
        real_time: bool = True,
        clock: Clock | None = None,
        rng: random.Random | None = None,
    ) -> None:
        config = IntegrationConfig(asset_id=asset_id, protocol="simulated", simulate=True)
        super().__init__(asset_id, config)
        self.rated_mw = rated_mw
        self.rated_mwh = rated_mwh
        self.chemistry = chemistry
        self.tick_interval_seconds = tick_interval_seconds
        self.real_time = real_time
        self._clock = clock or _utc_now
        self._rng = rng or random.Random()
        self._soc = _clamp(initial_soc, 0.05, 0.98)
        self._soh = initial_soh
        self._setpoint_mw = 0.0
        self._throughput_mwh = 0.0

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    def set_dispatch(self, mw: float) -> None:
        """Apply a dispatch setpoint immediately, clamped to +/- rated_mw."""
        self._setpoint_mw = _clamp(mw, -self.rated_mw, self.rated_mw)

    async def send_dispatch(self, mw: float) -> bool:
        self.set_dispatch(mw)
        return True

    def _integrate(self, dt: float) -> None:
        """Advance SOC, SOH and throughput by ``dt`` seconds of physics."""
        p = self._setpoint_mw
        self._soc = _clamp(self._soc - (p / self.rated_mwh) * (dt / 3600.0), 0.05, 0.98)
        throughput = abs(p) * (dt / 3600.0)
        self._throughput_mwh += throughput
        rate = self._DEGRADATION_MWH_PER_PCT.get(self.chemistry, 1500.0)
        self._soh = max(0.0, self._soh - (throughput / rate) * 0.01)

    def _build_telemetry(self) -> AssetTelemetry:
        now = self._clock()
        hour = now.hour + now.minute / 60.0
        ambient = 25.0 + 8.0 * math.sin(2.0 * math.pi * hour / 24.0)
        power = self._setpoint_mw
        temperature = ambient + abs(power) * 0.9 + self._rng.gauss(0.0, 0.3)
        soc_pct = self._soc * 100.0
        soh_pct = self._soh * 100.0

        alarm: str | None = None
        if temperature > 38.0:
            alarm = "THERMAL_WARNING"
        elif soc_pct < 15.0:
            alarm = "LOW_SOC_WARNING"
        elif self._rng.random() < 0.005:
            alarm = "CELL_IMBALANCE_MINOR"

        return AssetTelemetry(
            asset_id=self.asset_id,
            timestamp=now.isoformat(),
            soc_pct=soc_pct,
            power_mw=power,
            temperature_c=temperature,
            voltage_v=750.0 + self._soc * 250.0,
            soh_pct=soh_pct,
            alarm=alarm,
            connection_status="simulated",
        )

    async def stream(self) -> AsyncGenerator[AssetTelemetry, None]:
        while True:
            self._integrate(self.tick_interval_seconds)
            telemetry = self._build_telemetry()
            self._mark_telemetry()
            yield telemetry
            await asyncio.sleep(self.tick_interval_seconds if self.real_time else 0.0)


class SolarSimulator(AssetConnector):
    """Solar generation simulator (generation only; ``power_mw`` >= 0).

    Power follows an irradiance curve and only generates 06:00-20:00:
        P = rated_mw * max(0, sin(pi*(hour-6)/12)) * (0.85 + 0.15*random)
    """

    def __init__(
        self,
        asset_id: str,
        rated_mw: float,
        tick_interval_seconds: float = 5.0,
        real_time: bool = True,
        clock: Clock | None = None,
        rng: random.Random | None = None,
    ) -> None:
        config = IntegrationConfig(asset_id=asset_id, protocol="simulated", simulate=True)
        super().__init__(asset_id, config)
        self.rated_mw = rated_mw
        self.tick_interval_seconds = tick_interval_seconds
        self.real_time = real_time
        self._clock = clock or _utc_now
        self._rng = rng or random.Random()
        self._curtail_mw = rated_mw  # max allowed output; dispatch can curtail

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send_dispatch(self, mw: float) -> bool:
        # Solar can only curtail downward; treat the setpoint as an output cap.
        self._curtail_mw = _clamp(mw, 0.0, self.rated_mw)
        return True

    def generation_mw(self, hour: float) -> float:
        """Instantaneous generation (MW) for a given hour of day (0-24)."""
        if hour < 6.0 or hour >= 20.0:
            return 0.0
        irradiance = math.sin(math.pi * (hour - 6.0) / 12.0)
        if irradiance <= 0.0:
            return 0.0
        output = self.rated_mw * irradiance * (0.85 + 0.15 * self._rng.random())
        return min(output, self._curtail_mw)

    def _build_telemetry(self) -> AssetTelemetry:
        now = self._clock()
        hour = now.hour + now.minute / 60.0
        ambient = 25.0 + 8.0 * math.sin(2.0 * math.pi * hour / 24.0)
        power = self.generation_mw(hour)
        return AssetTelemetry(
            asset_id=self.asset_id,
            timestamp=now.isoformat(),
            soc_pct=0.0,  # no storage
            power_mw=power,
            temperature_c=ambient + power * 0.1 + self._rng.gauss(0.0, 0.2),
            voltage_v=0.0,
            soh_pct=100.0,
            alarm=None,
            connection_status="simulated",
        )

    async def stream(self) -> AsyncGenerator[AssetTelemetry, None]:
        while True:
            telemetry = self._build_telemetry()
            self._mark_telemetry()
            yield telemetry
            await asyncio.sleep(self.tick_interval_seconds if self.real_time else 0.0)
