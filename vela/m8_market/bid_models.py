"""Market bid data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BidType(Enum):
    ENERGY = "energy"
    REG_UP = "reg_up"
    REG_DOWN = "reg_down"
    SPIN = "spin"
    NONSPIN = "nonspin"
    CAPACITY = "capacity"


@dataclass
class EnergyBid:
    asset_id: str
    market: str
    interval_start: datetime
    interval_end: datetime
    mw: float
    price: float
    bid_type: BidType = BidType.ENERGY
    bid_id: str = ""
    submitted_at: datetime | None = None
    status: str = "pending"


@dataclass
class AncillaryBid:
    asset_id: str
    market: str
    interval_start: datetime
    service: str
    mw: float
    price: float
    bid_id: str = ""
    status: str = "pending"
