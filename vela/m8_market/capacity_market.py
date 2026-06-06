"""Capacity market participation: PJM RPM, ISO-NE FCM, NYISO ICAP."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple


class CapacityOffer(NamedTuple):
    asset_id: str
    market: str
    delivery_year: str            # e.g., "2025/26"
    offered_mw: float             # Unforced Capacity (UCAP)
    icap_mw: float                # Installed Capacity
    clearing_price: float         # $/MW-day
    annual_revenue: float         # $ per year
    performance_requirement: str  # Performance obligation description


@dataclass
class PJMRPMParticipant:
    """
    PJM Reliability Pricing Model (RPM) capacity market participation.

    Key concepts:
    - ICAP (Installed Capacity): nameplate capacity
    - UCAP (Unforced Capacity): ICAP * EFORd derating factor
    - Delivery Year: June 1 - May 31
    - BRA (Base Residual Auction): ~3 years forward
    - Incremental Auctions: adjustments closer to delivery
    - Performance requirement: 4-h duration minimum for storage
    """
    asset_id: str
    capacity_mwh: float
    power_mw: float
    min_duration_hours: float = 4.0  # PJM requires >= 4h for capacity credit
    eford: float = 0.02             # Equivalent Forced Outage Rate (derating)
    reliability_region: str = "MAAC"

    @property
    def icap_mw(self) -> float:
        """Installed Capacity (MW)."""
        return self.power_mw

    @property
    def ucap_mw(self) -> float:
        """Unforced Capacity = ICAP * (1 - EFORd)."""
        return self.icap_mw * (1 - self.eford)

    @property
    def duration_derating(self) -> float:
        """Duration derating for storage < 4 hours."""
        actual_duration = self.capacity_mwh / (self.power_mw + 1e-6)
        if actual_duration >= self.min_duration_hours:
            return 1.0
        return actual_duration / self.min_duration_hours

    def capacity_offer(
        self,
        delivery_year: str,
        clearing_price_per_mw_day: float,
        offer_price_per_mw_day: float | None = None,
    ) -> CapacityOffer:
        """
        Construct a PJM RPM capacity offer.

        Parameters
        ----------
        clearing_price_per_mw_day : float
            Market clearing price ($/MW-day)
        offer_price_per_mw_day : float, optional
            Asset's submitted offer price. Defaults to cost-of-new-entry-based price.
        """
        offered_ucap = self.ucap_mw * self.duration_derating
        annual_revenue = offered_ucap * clearing_price_per_mw_day * 365

        return CapacityOffer(
            asset_id=self.asset_id,
            market="PJM_RPM",
            delivery_year=delivery_year,
            offered_mw=offered_ucap,
            icap_mw=self.icap_mw,
            clearing_price=clearing_price_per_mw_day,
            annual_revenue=annual_revenue,
            performance_requirement=(
                f"Must provide {self.min_duration_hours}h at rated power during "
                f"Performance Assessment Hours. EFORd = {self.eford:.1%}."
            ),
        )

    def capacity_revenue_forecast(
        self,
        price_scenarios: list[float],
        delivery_years: list[str],
    ) -> dict[str, float]:
        """Forecast capacity revenue over multiple delivery years."""
        revenues = {}
        for year, price in zip(delivery_years, price_scenarios):
            offer = self.capacity_offer(year, price)
            revenues[year] = offer.annual_revenue
        return revenues


@dataclass
class ISONEFCMParticipant:
    """
    ISO-NE Forward Capacity Market (FCM) participation.

    ISO-NE Forward Capacity Market:
    - Annual auction ~3.5 years ahead of delivery
    - Capacity Commitment Period: June 1 - May 31
    - Resources must meet Performance Incentive requirements
    - "Pay-for-performance" model with bonuses/penalties
    """
    asset_id: str
    capacity_mwh: float
    power_mw: float
    qualified_capacity_mw: float | None = None  # If None, uses power_mw

    @property
    def net_capability_mw(self) -> float:
        """Net Capability (capacity offered into FCM)."""
        return self.qualified_capacity_mw or self.power_mw

    def fcm_offer(
        self,
        delivery_year: str,
        clearing_price_per_kw_month: float,
    ) -> CapacityOffer:
        """
        Build ISO-NE FCM offer.

        ISO-NE prices are typically in $/kW-month.
        """
        # Convert to $/MW-month then annual
        price_per_mw_month = clearing_price_per_kw_month * 1000
        annual_revenue = self.net_capability_mw * price_per_mw_month * 12

        return CapacityOffer(
            asset_id=self.asset_id,
            market="ISONE_FCM",
            delivery_year=delivery_year,
            offered_mw=self.net_capability_mw,
            icap_mw=self.power_mw,
            clearing_price=clearing_price_per_kw_month,
            annual_revenue=annual_revenue,
            performance_requirement=(
                "Must respond during Capacity Scarcity Conditions. "
                "Performance Incentive Rate applies ±$0.05/kWh."
            ),
        )


@dataclass
class CapacityMarketAnalyzer:
    """
    Multi-market capacity value analysis.

    Compares capacity market revenues across PJM, ISO-NE, NYISO
    and recommends optimal capacity market strategy.
    """

    def compare_markets(
        self,
        asset_power_mw: float,
        asset_capacity_mwh: float,
        market_prices: dict[str, float],  # market -> price in $/MW-year
    ) -> dict[str, float]:
        """
        Compare annual capacity revenues across markets.

        Parameters
        ----------
        market_prices : dict
            Mapping of market name to clearing price in $/MW-year
        """
        revenues = {}
        duration_hours = asset_capacity_mwh / (asset_power_mw + 1e-6)
        duration_credit = min(1.0, duration_hours / 4.0)

        for market, price_per_mw_year in market_prices.items():
            revenues[market] = asset_power_mw * duration_credit * price_per_mw_year

        if revenues:
            best_market = max(revenues, key=revenues.get)
            revenues["_best_market"] = best_market  # type: ignore[assignment]
            revenues["_best_revenue"] = revenues[best_market]

        return revenues

    def lcr_analysis(
        self,
        asset_power_mw: float,
        capacity_price_per_mw_year: float,
        annual_om_cost: float,
        discount_rate: float = 0.08,
        project_life_years: int = 20,
    ) -> dict[str, float]:
        """
        Levelized Cost of Reliability (LCR) analysis.

        Computes NPV of capacity revenue stream.
        """
        annual_revenue = asset_power_mw * capacity_price_per_mw_year
        net_annual = annual_revenue - annual_om_cost

        # NPV of annuity
        if discount_rate > 0:
            npv_factor = (1 - (1 + discount_rate) ** -project_life_years) / discount_rate
        else:
            npv_factor = float(project_life_years)

        npv = net_annual * npv_factor
        lcr = annual_om_cost / (asset_power_mw + 1e-6)

        return {
            "annual_capacity_revenue": annual_revenue,
            "annual_net_revenue": net_annual,
            "npv_20yr": npv,
            "lcr_per_mw_year": lcr,
            "payback_years": annual_om_cost / (annual_revenue + 1e-6) if annual_revenue > 0 else float("inf"),
        }
