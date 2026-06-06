"""
Dashboard data preparation layer for VPP Streamlit/web dashboards.

Transforms raw operational data into pre-aggregated metrics and
time series for efficient dashboard rendering.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np


@dataclass
class DashboardMetric:
    name: str
    value: float
    unit: str
    delta: Optional[float] = None     # Change vs previous period
    delta_pct: Optional[float] = None
    trend: Optional[List[float]] = None   # Sparkline data


@dataclass
class DashboardPayload:
    timestamp: float
    kpis: List[DashboardMetric]
    charts: Dict[str, Any]
    alerts: List[Dict[str, str]]
    fleet_map: List[Dict[str, Any]]


class DashboardDataEngine:
    """
    Prepares dashboard data payloads for VPP operator interfaces.

    Aggregates fleet telemetry, market prices, and revenue data
    into display-ready structures.
    """

    def __init__(self) -> None:
        self._previous_kpis: Dict[str, float] = {}

    def build_fleet_kpis(
        self,
        active_mw: float,
        available_mw: float,
        avg_soc_pct: float,
        hourly_revenue_usd: float,
        active_events: int,
    ) -> List[DashboardMetric]:
        """Build top-level KPI cards for main dashboard."""
        metrics = [
            DashboardMetric("Active Power", active_mw, "MW",
                            delta=active_mw - self._previous_kpis.get("active_mw", active_mw)),
            DashboardMetric("Available Capacity", available_mw, "MW"),
            DashboardMetric("Fleet SOC", avg_soc_pct, "%"),
            DashboardMetric("Revenue (1H)", hourly_revenue_usd, "$/h",
                            delta=hourly_revenue_usd - self._previous_kpis.get("revenue", hourly_revenue_usd)),
            DashboardMetric("Active Events", float(active_events), ""),
        ]
        self._previous_kpis.update({
            "active_mw": active_mw, "revenue": hourly_revenue_usd
        })
        return metrics

    def build_price_chart(
        self, hourly_lmps: List[float], timestamps: List[float]
    ) -> Dict[str, Any]:
        """Format LMP time series for chart rendering."""
        return {
            "type": "line",
            "x": timestamps,
            "y": hourly_lmps,
            "title": "Day-Ahead LMP ($/MWh)",
            "ymin": 0.0,
            "ymax": float(max(hourly_lmps)) * 1.2 if hourly_lmps else 100.0,
        }

    def build_soc_chart(
        self, asset_ids: List[str], soc_values: List[float]
    ) -> Dict[str, Any]:
        """Format fleet SOC bar chart data."""
        return {
            "type": "bar",
            "x": asset_ids,
            "y": soc_values,
            "title": "Fleet State of Charge (%)",
            "ymin": 0, "ymax": 100,
        }

    def build_fleet_map(
        self,
        assets: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Format asset location + status data for map rendering."""
        return [
            {
                "asset_id": a["asset_id"],
                "lat": a.get("lat", 30.0),
                "lon": a.get("lon", -97.0),
                "status": a.get("status", "online"),
                "power_mw": a.get("power_mw", 0.0),
                "soc_pct": a.get("soc_pct", 50.0),
                "color": "green" if a.get("status") == "online" else "red",
            }
            for a in assets
        ]

    def build_payload(
        self,
        active_mw: float,
        available_mw: float,
        avg_soc_pct: float,
        hourly_revenue_usd: float,
        active_events: int,
        hourly_lmps: List[float],
        timestamps: List[float],
        asset_socs: Dict[str, float],
        asset_locations: List[Dict[str, Any]],
        alert_messages: List[Dict[str, str]],
    ) -> DashboardPayload:
        """Build complete dashboard payload for one refresh cycle."""
        import time
        return DashboardPayload(
            timestamp=time.time(),
            kpis=self.build_fleet_kpis(active_mw, available_mw, avg_soc_pct, hourly_revenue_usd, active_events),
            charts={
                "lmp": self.build_price_chart(hourly_lmps, timestamps),
                "soc": self.build_soc_chart(list(asset_socs.keys()), list(asset_socs.values())),
            },
            alerts=alert_messages,
            fleet_map=self.build_fleet_map(asset_locations),
        )
