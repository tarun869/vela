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


# ---------------------------------------------------------------------------
# Extended bid models used by tests and API
# ---------------------------------------------------------------------------


@dataclass
class MarketBid:
    """A single-price, single-quantity bid for any market service."""

    bid_id: str
    asset_id: str
    market: str
    service: str                 # "energy" | "reg_up" | "reg_down" | "spin" | "non_spin"
    quantity_mw: float
    price_usd_mwh: float
    interval_start: datetime
    interval_end: datetime
    status: str = "pending"
    submitted_at: datetime | None = None


@dataclass
class BidTranche:
    """One price-quantity step on a bid curve."""

    quantity_mw: float
    price_usd_mwh: float


@dataclass
class BidCurve:
    """A stepped bid curve composed of multiple tranches for a single asset."""

    asset_id: str
    tranches: list[BidTranche] = field(default_factory=list)
    service: str = "energy"
    market: str = "CAISO"

    @property
    def total_quantity_mw(self) -> float:
        return sum(t.quantity_mw for t in self.tranches)

    def min_price(self) -> float:
        return min(t.price_usd_mwh for t in self.tranches) if self.tranches else 0.0

    def max_price(self) -> float:
        return max(t.price_usd_mwh for t in self.tranches) if self.tranches else 0.0


def build_price_quantity_stack(
    asset_id: str,
    discharge_mw: list[float],
    offer_prices: list[float],
    service: str = "energy",
    market: str = "CAISO",
) -> BidCurve:
    """Build a BidCurve from optimizer dispatch and price arrays.

    Each (discharge_mw[i], offer_prices[i]) pair becomes one BidTranche.
    Tranches are sorted ascending by price so the curve is monotone.
    """
    if len(discharge_mw) != len(offer_prices):
        raise ValueError("discharge_mw and offer_prices must have equal length")

    tranches = [
        BidTranche(quantity_mw=float(mw), price_usd_mwh=float(p))
        for mw, p in sorted(zip(discharge_mw, offer_prices), key=lambda x: x[1])
        if mw > 0.0
    ]
    return BidCurve(asset_id=asset_id, tranches=tranches, service=service, market=market)
