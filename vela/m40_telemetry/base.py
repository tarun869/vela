"""Abstract connector interface shared by simulators and real integrations.

Every connector — simulated or hardware — implements :class:`AssetConnector`, so
the :class:`~vela.m40_telemetry.fleet_manager.FleetManager` can treat them
interchangeably and swap implementations with a single config flag.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from .models import AssetTelemetry, IntegrationConfig

# A connector is considered healthy if it produced telemetry within this window.
HEALTH_TIMEOUT_SECONDS = 30.0


class AssetConnector(ABC):
    """Uniform async interface to a single physical (or simulated) asset."""

    def __init__(self, asset_id: str, config: IntegrationConfig) -> None:
        self.asset_id = asset_id
        self.config = config
        self._last_telemetry_ts: float | None = None

    @abstractmethod
    async def connect(self) -> bool:
        """Establish the underlying connection. Returns True on success."""

    @abstractmethod
    def stream(self) -> AsyncGenerator[AssetTelemetry, None]:
        """Yield :class:`AssetTelemetry` continuously until cancelled."""

    @abstractmethod
    async def send_dispatch(self, mw: float) -> bool:
        """Send a dispatch setpoint to the asset. Returns True if accepted."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the underlying connection."""

    def _mark_telemetry(self) -> None:
        """Record that telemetry was just produced (drives :meth:`is_healthy`)."""
        self._last_telemetry_ts = time.monotonic()

    def is_healthy(self) -> bool:
        """True if the last telemetry sample arrived < 30 seconds ago."""
        if self._last_telemetry_ts is None:
            return False
        return (time.monotonic() - self._last_telemetry_ts) < HEALTH_TIMEOUT_SECONDS
