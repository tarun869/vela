"""
Revenue attribution and analysis for VPP dispatch strategies.

Decomposes revenue by service type, time period, market, and asset,
enabling performance attribution and revenue forecasting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class RevenueRecord:
    timestamp: str
    asset_id: str
    site_id: str
    service: str           # "energy", "reg_up", "reg_dn", "spin", "capacity", "dr"
    energy_kwh: float
    price_usd_kwh: float
    revenue_usd: float
    market: str            # ISO/RTO name
    period_type: str       # "peak", "off_peak", "super_peak", "shoulder"


@dataclass
class RevenueAttribution:
    total_revenue_usd: float
    by_service: Dict[str, float]
    by_asset: Dict[str, float]
    by_period: Dict[str, float]
    by_market: Dict[str, float]
    top_revenue_hours: List[Tuple[str, float]]
    revenue_per_mwh: float
    capacity_factor: float


class RevenueAnalytics:
    """
    Revenue analytics engine for VPP portfolio.
    """

    def __init__(self) -> None:
        self._records: List[RevenueRecord] = []

    def add_records(self, records: List[RevenueRecord]) -> None:
        self._records.extend(records)

    def attribute_revenue(
        self,
        since: Optional[str] = None,
        asset_filter: Optional[str] = None,
    ) -> RevenueAttribution:
        """Compute revenue attribution across dimensions."""
        records = self._records
        if since:
            records = [r for r in records if r.timestamp >= since]
        if asset_filter:
            records = [r for r in records if r.asset_id == asset_filter]

        if not records:
            return RevenueAttribution(
                total_revenue_usd=0, by_service={}, by_asset={},
                by_period={}, by_market={}, top_revenue_hours=[],
                revenue_per_mwh=0, capacity_factor=0,
            )

        by_service: Dict[str, float] = {}
        by_asset: Dict[str, float] = {}
        by_period: Dict[str, float] = {}
        by_market: Dict[str, float] = {}
        total = 0.0
        total_kwh = 0.0

        for r in records:
            by_service[r.service] = by_service.get(r.service, 0.0) + r.revenue_usd
            by_asset[r.asset_id] = by_asset.get(r.asset_id, 0.0) + r.revenue_usd
            by_period[r.period_type] = by_period.get(r.period_type, 0.0) + r.revenue_usd
            by_market[r.market] = by_market.get(r.market, 0.0) + r.revenue_usd
            total += r.revenue_usd
            total_kwh += r.energy_kwh

        # Top revenue hours
        sorted_records = sorted(records, key=lambda x: x.revenue_usd, reverse=True)
        top_hours = [(r.timestamp, r.revenue_usd) for r in sorted_records[:10]]

        revenue_per_mwh = (total / (total_kwh / 1000.0)) if total_kwh > 0 else 0.0

        return RevenueAttribution(
            total_revenue_usd=total,
            by_service=by_service,
            by_asset=by_asset,
            by_period=by_period,
            by_market=by_market,
            top_revenue_hours=top_hours,
            revenue_per_mwh=revenue_per_mwh,
            capacity_factor=0.0,
        )

    def revenue_decomposition(
        self, base_scenario_revenue: float, actual_revenue: float
    ) -> Dict[str, float]:
        """Decompose revenue variance into price, volume, and mix effects."""
        total_variance = actual_revenue - base_scenario_revenue
        price_effect = total_variance * 0.6   # Simplified decomposition
        volume_effect = total_variance * 0.3
        mix_effect = total_variance * 0.1
        return {
            "price_effect": price_effect,
            "volume_effect": volume_effect,
            "mix_effect": mix_effect,
            "total_variance": total_variance,
        }

    def rolling_revenue_stats(
        self, window_days: int = 30
    ) -> Dict[str, float]:
        """Compute rolling revenue statistics over the last N days."""
        if not self._records:
            return {}
        revenues = [r.revenue_usd for r in self._records[-window_days * 24:]]
        rev_arr = np.array(revenues)
        return {
            "mean_usd": float(rev_arr.mean()),
            "std_usd": float(rev_arr.std()),
            "p10_usd": float(np.percentile(rev_arr, 10)),
            "p90_usd": float(np.percentile(rev_arr, 90)),
            "total_usd": float(rev_arr.sum()),
        }
