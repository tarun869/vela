"""Portfolio data models: asset groupings, programs, and revenue tracking."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass
class AssetProfile:
    """Physical characteristics and operational parameters of a single asset."""
    asset_id: str
    asset_type: Literal["battery", "flywheel", "pumped_hydro", "compressed_air", "ev_fleet", "demand_response"]
    capacity_mwh: float
    power_mw: float
    rte: float = 0.92  # round-trip efficiency
    soc_min: float = 0.05
    soc_max: float = 0.95
    charge_efficiency: float = 0.96
    discharge_efficiency: float = 0.96
    cycle_life: int = 4000  # total cycles at rated capacity
    calendar_life_years: int = 15
    degradation_rate_per_cycle: float = 0.0001  # fractional capacity loss per cycle
    site_id: str | None = None
    iso: str = "CAISO"
    pricing_node: str = "TH_NP15_GEN-APND"

    @property
    def usable_capacity_mwh(self) -> float:
        return self.capacity_mwh * (self.soc_max - self.soc_min)


@dataclass
class Program:
    """A market program that assets can be enrolled in."""
    program_id: str
    name: str
    program_type: Literal[
        "energy_arbitrage",
        "regulation",
        "spinning_reserve",
        "demand_response",
        "capacity",
        "virtual_peaker",
    ]
    market: str
    min_asset_mw: float = 0.0
    max_asset_mw: float | None = None
    min_portfolio_mw: float = 0.0
    payment_structure: Literal["capacity", "energy", "performance"] = "performance"
    active: bool = True


@dataclass
class Enrollment:
    """Links an asset to a program with contract terms."""
    enrollment_id: str
    asset_id: str
    program_id: str
    enrolled_mw: float
    enrolled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    status: Literal["active", "pending", "expired", "terminated"] = "active"
    contract_id: str | None = None

    @property
    def is_active(self) -> bool:
        if self.status != "active":
            return False
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False
        return True


@dataclass
class RevenueRecord:
    """Single revenue event attributed to an asset and program."""
    record_id: str
    asset_id: str
    program_id: str | None
    interval_start: datetime
    revenue_usd: float
    service: str  # "energy", "reg_up", "reg_down", "spin", "dr"
    energy_mwh: float
    lmp: float

    @property
    def revenue_per_mwh(self) -> float:
        if self.energy_mwh == 0:
            return 0.0
        return self.revenue_usd / self.energy_mwh


@dataclass
class Portfolio:
    """Collection of assets managed as a VPP."""
    portfolio_id: str
    name: str
    assets: list[AssetProfile] = field(default_factory=list)
    programs: list[Program] = field(default_factory=list)
    enrollments: list[Enrollment] = field(default_factory=list)
    revenue_records: list[RevenueRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_capacity_mwh(self) -> float:
        return sum(a.capacity_mwh for a in self.assets)

    @property
    def total_power_mw(self) -> float:
        return sum(a.power_mw for a in self.assets)

    @property
    def asset_ids(self) -> list[str]:
        return [a.asset_id for a in self.assets]

    def total_revenue(self, since: datetime | None = None) -> float:
        records = self.revenue_records
        if since:
            records = [r for r in records if r.interval_start >= since]
        return sum(r.revenue_usd for r in records)

    def add_asset(self, asset: AssetProfile) -> None:
        self.assets.append(asset)

    def remove_asset(self, asset_id: str) -> bool:
        before = len(self.assets)
        self.assets = [a for a in self.assets if a.asset_id != asset_id]
        return len(self.assets) < before
