"""m40_telemetry — live asset integration & telemetry streaming.

Connects to real battery/solar/EV assets via industry protocols (SunSpec Modbus,
Tesla Gateway, generic REST) and provides interchangeable simulators for demos.
All connectors share the :class:`AssetConnector` interface, so the
:class:`FleetManager` can swap real hardware for a simulator via one config flag.
"""
from __future__ import annotations

from .base import AssetConnector
from .fleet_manager import FleetManager, build_connector
from .generic_rest_connector import GenericRESTConnector
from .models import AssetTelemetry, IntegrationConfig, PriceTick
from .price_feed import ERCOTHistoricalReplay
from .simulator import BESSSimulator, SolarSimulator
from .sunspec_connector import SunSpecModbusConnector
from .tesla_connector import TeslaGatewayConnector

__all__ = [
    "AssetConnector",
    "AssetTelemetry",
    "PriceTick",
    "IntegrationConfig",
    "BESSSimulator",
    "SolarSimulator",
    "SunSpecModbusConnector",
    "TeslaGatewayConnector",
    "GenericRESTConnector",
    "ERCOTHistoricalReplay",
    "FleetManager",
    "build_connector",
]
