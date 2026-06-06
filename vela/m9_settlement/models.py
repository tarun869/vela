"""Settlement data models for energy market settlement."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SettlementStatus(Enum):
    PENDING = "pending"
    PRELIMINARY = "preliminary"
    FINAL = "final"
    DISPUTED = "disputed"


class ServiceType(Enum):
    ENERGY = "energy"
    REG_UP = "reg_up"
    REG_DOWN = "reg_down"
    SPIN = "spin"
    NONSPIN = "nonspin"
    CAPACITY = "capacity"


@dataclass
class MeterReading:
    """Interval meter data reading."""
    asset_id: str
    interval_start: datetime
    interval_end: datetime
    energy_mwh: float          # Positive = generation/discharge, negative = consumption/charge
    reactive_mvar: float = 0.0
    meter_id: str = ""
    quality_flag: str = "good"  # good, estimated, suspect, bad


@dataclass
class SettlementCharge:
    """A single line-item charge or credit on a settlement statement."""
    charge_id: str
    service_type: ServiceType
    interval_start: datetime
    quantity_mwh: float
    price_per_mwh: float
    amount: float              # = quantity * price (negative = credit)
    charge_type: str           # "energy", "imbalance", "capacity", "ancillary", "tx"
    description: str = ""

    def __post_init__(self) -> None:
        # Auto-compute amount if not set
        if self.amount == 0.0 and self.quantity_mwh != 0.0:
            self.amount = self.quantity_mwh * self.price_per_mwh


@dataclass
class SettlementAccount:
    """
    A settlement account aggregating charges for a portfolio.

    Used for multi-asset fleet settlement tracking.
    """
    account_id: str
    participant_id: str
    market: str
    settlement_period: str     # e.g., "2025-06"
    charges: list[SettlementCharge] = field(default_factory=list)
    meter_readings: list[MeterReading] = field(default_factory=list)
    status: SettlementStatus = SettlementStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    finalized_at: datetime | None = None

    @property
    def total_revenue(self) -> float:
        """Total revenue (negative charges = revenue)."""
        return -sum(c.amount for c in self.charges)

    @property
    def total_energy_mwh(self) -> float:
        return sum(abs(r.energy_mwh) for r in self.meter_readings)

    @property
    def net_energy_mwh(self) -> float:
        return sum(r.energy_mwh for r in self.meter_readings)

    def add_charge(self, charge: SettlementCharge) -> None:
        self.charges.append(charge)

    def add_reading(self, reading: MeterReading) -> None:
        self.meter_readings.append(reading)

    def summary_by_service(self) -> dict[str, float]:
        """Revenue breakdown by service type."""
        by_service: dict[str, float] = {}
        for charge in self.charges:
            key = charge.service_type.value
            by_service[key] = by_service.get(key, 0.0) + (-charge.amount)
        return by_service

    def finalize(self) -> None:
        self.status = SettlementStatus.FINAL
        self.finalized_at = datetime.utcnow()


@dataclass
class DisputeRecord:
    """Record of a settlement dispute."""
    dispute_id: str
    account_id: str
    disputed_charges: list[str]   # charge_ids
    reason: str
    submitted_at: datetime
    amount_disputed: float
    resolution: str = ""
    resolved_at: datetime | None = None
    status: str = "open"
