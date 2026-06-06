"""ERCOT ancillary service bidding logic and qualification tracking."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple

import numpy as np

from .bid_models import AncillaryBid

logger = logging.getLogger(__name__)


# ERCOT AS products and their characteristics
ERCOT_AS_PRODUCTS = {
    "ECRS":     {"min_mw": 1.0, "response_time_min": 10, "duration_h": 2.0, "priority": 1},
    "REG_UP":   {"min_mw": 0.1, "response_time_min": 0,  "duration_h": 1.0, "priority": 2},
    "REG_DOWN": {"min_mw": 0.1, "response_time_min": 0,  "duration_h": 1.0, "priority": 2},
    "RRS":      {"min_mw": 0.1, "response_time_min": 10, "duration_h": 0.5, "priority": 3},
    "NSRS":     {"min_mw": 0.1, "response_time_min": 30, "duration_h": 0.5, "priority": 4},
    "FFR":      {"min_mw": 1.0, "response_time_min": 0,  "duration_h": 0.1, "priority": 1},
}

# Typical ERCOT ancillary service procurement targets (MW) — varies by season
ERCOT_AS_TARGETS = {
    "ECRS": 2500.0,
    "REG_UP": 300.0,
    "REG_DOWN": 300.0,
    "RRS": 2800.0,
    "NSRS": 1000.0,
    "FFR": 1600.0,
}


class ERCOTASAward(NamedTuple):
    asset_id: str
    product: str
    awarded_mw: float
    clearing_price: float     # $/MWh
    interval_start: datetime
    total_revenue: float      # = awarded_mw * clearing_price * duration_h


@dataclass
class ERCOTQualification:
    """
    Tracks ERCOT ancillary service qualification for a resource.

    Resources must pass telemetry tests and meet response time requirements.
    """
    asset_id: str
    qualified_products: set[str] = field(default_factory=set)
    telemetry_compliant: bool = True
    last_test_date: datetime | None = None
    response_time_s: dict[str, float] = field(default_factory=dict)  # product -> seconds

    def is_qualified(self, product: str) -> bool:
        return (
            product in self.qualified_products
            and self.telemetry_compliant
        )

    def qualify_for_product(
        self,
        product: str,
        response_time_s: float,
        capacity_mwh: float,
        power_mw: float,
    ) -> bool:
        """Check if asset meets qualification requirements for a given AS product."""
        if product not in ERCOT_AS_PRODUCTS:
            return False
        spec = ERCOT_AS_PRODUCTS[product]

        if power_mw < spec["min_mw"]:
            logger.warning("Asset %s: power_mw %.1f < min %.1f for %s", self.asset_id, power_mw, spec["min_mw"], product)
            return False

        required_duration = spec["duration_h"]
        actual_duration = capacity_mwh / (power_mw + 1e-6)
        if actual_duration < required_duration:
            logger.warning(
                "Asset %s: duration %.2fh < required %.2fh for %s",
                self.asset_id, actual_duration, required_duration, product
            )
            return False

        # Response time check
        required_response_min = spec["response_time_min"]
        response_min = response_time_s / 60.0
        if required_response_min > 0 and response_min > required_response_min:
            logger.warning(
                "Asset %s: response time %.1f min > required %.1f min for %s",
                self.asset_id, response_min, required_response_min, product
            )
            return False

        self.qualified_products.add(product)
        self.response_time_s[product] = response_time_s
        self.last_test_date = datetime.utcnow()
        logger.info("Asset %s qualified for %s", self.asset_id, product)
        return True


@dataclass
class ERCOTASBidder:
    """
    ERCOT ancillary service bid submission and optimization.

    ERCOT AS bids are submitted per interval (15-minute for real-time, hourly for day-ahead).
    The ERCOT market clears AS products in the following order:
    1. ECRS (ERCOT Contingency Reserve Service)
    2. Regulation Up/Down
    3. RRS (Responsive Reserve Service)
    4. Non-Spinning Reserve

    Battery storage can stack multiple AS products simultaneously (within capability constraints).
    """
    asset_id: str
    capacity_mwh: float
    power_mw: float
    rte: float = 0.92
    soc_min: float = 0.15   # Higher minimum for AS obligations
    soc_max: float = 0.85   # Lower maximum for AS obligations
    qualification: ERCOTQualification = field(default_factory=lambda: ERCOTQualification(""))

    def __post_init__(self) -> None:
        if not self.qualification.asset_id:
            self.qualification = ERCOTQualification(self.asset_id)

    def available_as_mw(
        self,
        current_soc: float,
        product: str,
        dt_hours: float = 1.0,
    ) -> float:
        """
        Compute available MW for a given AS product given current SOC.

        For discharge-direction services (REG_UP, RRS, ECRS, FFR):
            Available MW limited by SOC above soc_min

        For charge-direction services (REG_DOWN):
            Available MW limited by SOC below soc_max
        """
        spec = ERCOT_AS_PRODUCTS.get(product, {})
        duration_h = spec.get("duration_h", 1.0)

        if product in ("REG_UP", "RRS", "ECRS", "FFR"):
            energy_available = (current_soc - self.soc_min) * self.capacity_mwh
            return min(self.power_mw, energy_available / (duration_h + 1e-6))
        elif product == "REG_DOWN":
            energy_available = (self.soc_max - current_soc) * self.capacity_mwh
            return min(self.power_mw, energy_available / (duration_h + 1e-6))
        else:  # NSRS
            energy_available = (current_soc - self.soc_min) * self.capacity_mwh
            return min(self.power_mw, energy_available / (duration_h + 1e-6))

    def build_dam_as_bids(
        self,
        trading_date: datetime,
        current_soc_profile: list[float],    # Hourly SOC forecast
        as_price_forecast: dict[str, list[float]],  # product -> hourly price
        lmp_forecast: list[float],
        horizon: int = 24,
    ) -> list[AncillaryBid]:
        """
        Build day-ahead AS bids for all qualified products.

        Prioritizes AS products by expected value, respecting stacking constraints.
        """
        bids = []
        T = min(horizon, len(current_soc_profile))

        for t in range(T):
            interval_start = trading_date + timedelta(hours=t)
            soc = current_soc_profile[t]
            remaining_mw = self.power_mw

            # Process products in priority order
            for product, spec in sorted(
                ERCOT_AS_PRODUCTS.items(),
                key=lambda x: x[1]["priority"]
            ):
                if not self.qualification.is_qualified(product):
                    continue

                avail = self.available_as_mw(soc, product)
                avail = min(avail, remaining_mw)

                if product in as_price_forecast:
                    price = as_price_forecast[product][t] if t < len(as_price_forecast[product]) else 0.0
                else:
                    price = 0.0

                min_mw = spec["min_mw"]
                if avail < min_mw or price < 0.5:  # Skip if insufficient capacity or low value
                    continue

                # Opportunity cost vs energy
                energy_opportunity = abs(lmp_forecast[t] - 35.0) * spec["duration_h"]
                if price < energy_opportunity * 0.5:
                    continue  # Energy arbitrage is more valuable

                bids.append(AncillaryBid(
                    asset_id=self.asset_id,
                    market="ERCOT_DAM",
                    interval_start=interval_start,
                    service=product,
                    mw=round(avail * 0.8, 2),  # Bid 80% to leave buffer
                    price=round(price * 0.95, 2),  # Slight underbid to ensure clearing
                    bid_id=str(uuid.uuid4())[:8],
                    status="pending",
                ))
                remaining_mw -= avail * 0.8

                if remaining_mw < min_mw:
                    break

        logger.info(
            "Built %d ERCOT AS bids for %s on %s",
            len(bids), self.asset_id, trading_date.date()
        )
        return bids

    def simulate_awards(
        self,
        bids: list[AncillaryBid],
        clearing_prices: dict[str, list[float]],  # product -> hourly clearing price
    ) -> list[ERCOTASAward]:
        """
        Simulate which bids would be awarded given clearing prices.

        A bid is awarded if bid_price <= clearing_price.
        """
        awards = []
        for bid in bids:
            product = bid.service
            if product not in clearing_prices:
                continue
            hour = bid.interval_start.hour
            if hour >= len(clearing_prices[product]):
                continue
            clearing_price = clearing_prices[product][hour]
            if bid.price <= clearing_price:
                duration_h = ERCOT_AS_PRODUCTS[product]["duration_h"]
                awards.append(ERCOTASAward(
                    asset_id=bid.asset_id,
                    product=product,
                    awarded_mw=bid.mw,
                    clearing_price=clearing_price,
                    interval_start=bid.interval_start,
                    total_revenue=bid.mw * clearing_price * duration_h,
                ))
        return awards
