"""Core data models for system state."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AssetStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    CURTAILED = "curtailed"
    FAULT = "fault"
    MAINTENANCE = "maintenance"


@dataclass
class AssetState:
    asset_id: str
    asset_type: str
    status: AssetStatus
    power_mw: float
    soc: float | None
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_stale(self, max_age_seconds: float = 300.0) -> bool:
        """Return True if this state has not been updated within max_age_seconds."""
        age = (datetime.now(timezone.utc) - self.last_updated).total_seconds()
        return age > max_age_seconds


@dataclass
class GridState:
    timestamp: datetime
    frequency_hz: float = 60.0
    voltage_pu: float = 1.0
    net_load_mw: float = 0.0
    renewable_fraction: float = 0.0
    area_control_error_mw: float = 0.0  # ACE = NIA - 10B * Δf

    @property
    def is_normal(self) -> bool:
        return (
            59.95 <= self.frequency_hz <= 60.05
            and 0.95 <= self.voltage_pu <= 1.05
        )


@dataclass
class MarketState:
    timestamp: datetime
    market: str
    lmp: float = 0.0
    reg_up_price: float = 0.0
    reg_down_price: float = 0.0
    spin_price: float = 0.0
    nonspin_price: float = 0.0
    capacity_price: float = 0.0
    node: str = ""

    @property
    def best_ancillary_price(self) -> float:
        return max(
            self.reg_up_price,
            self.reg_down_price,
            self.spin_price,
            self.nonspin_price,
        )

    @property
    def total_value_score(self) -> float:
        """Weighted opportunity score for dispatch decision."""
        return self.lmp + 0.5 * self.best_ancillary_price


@dataclass
class DispatchCommand:
    """A dispatch instruction sent to an asset."""
    asset_id: str
    power_mw: float                     # Target power (+ = discharge/generate, - = charge)
    duration_hours: float
    service: str = "energy"             # "energy", "reg_up", "reg_down", "spin"
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    command_id: str = ""

    @property
    def is_charge(self) -> bool:
        return self.power_mw < 0

    @property
    def is_discharge(self) -> bool:
        return self.power_mw > 0


@dataclass
class SettlementRecord:
    """A market settlement record for a single interval."""
    interval_start: datetime
    asset_id: str
    market: str
    service: str
    scheduled_mwh: float        # What we committed to
    metered_mwh: float          # What we actually delivered
    price_usd_per_mwh: float
    revenue_usd: float = 0.0
    imbalance_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.revenue_usd == 0.0:
            self.revenue_usd = self.metered_mwh * self.price_usd_per_mwh
        if self.imbalance_usd == 0.0:
            imbalance_mwh = self.metered_mwh - self.scheduled_mwh
            # Imbalance penalty: charge for deviations (simplified)
            self.imbalance_usd = abs(imbalance_mwh) * self.price_usd_per_mwh * 0.10
