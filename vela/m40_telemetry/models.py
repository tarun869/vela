"""Dataclasses for the m40_telemetry asset-integration module."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ConnectionStatus = Literal["connected", "simulated", "error"]
IntervalType = Literal["real_time", "day_ahead", "historical_replay"]
Protocol = Literal[
    "sunspec_modbus",
    "tesla_gateway",
    "generic_rest",
    "ocpp",
    "openadr",
    "simulated",
]


@dataclass
class AssetTelemetry:
    """A single telemetry sample from one asset."""

    asset_id: str
    timestamp: str  # ISO 8601 UTC
    soc_pct: float  # 0-100
    power_mw: float  # positive=discharge, negative=charge, 0=idle
    temperature_c: float
    voltage_v: float
    soh_pct: float  # state of health, 0-100
    alarm: str | None = None
    connection_status: ConnectionStatus = "simulated"


@dataclass
class PriceTick:
    """A single market price observation (LMP) for a settlement node."""

    timestamp: str
    node: str
    lmp_per_mwh: float
    energy_component: float
    congestion_component: float
    loss_component: float
    interval_type: IntervalType = "real_time"


@dataclass
class IntegrationConfig:
    """Connection configuration for a single asset."""

    asset_id: str
    protocol: Protocol
    host: str | None = None
    port: int | None = None
    api_key: str | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)
    simulate: bool = False
