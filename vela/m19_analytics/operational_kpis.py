"""
Operational KPI calculation for VPP fleet management.

Tracks availability, reliability, performance, and efficiency metrics
per NERC, IEC, and industry standards.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class AssetKPIs:
    asset_id: str
    period: str
    # Availability metrics
    availability_pct: float          # % time available for dispatch
    equivalent_availability_pct: float  # Capacity-weighted availability
    forced_outage_rate_pct: float    # Unplanned outages
    planned_outage_rate_pct: float   # Scheduled maintenance
    # Performance metrics
    capacity_factor_pct: float       # Actual / potential generation
    response_success_rate_pct: float # Successful dispatch responses
    avg_response_time_s: float       # Average response time to dispatch
    # Reliability
    mean_time_between_failures_h: float  # MTBF
    mean_time_to_repair_h: float         # MTTR
    # Financial
    revenue_per_mw_usd: float
    cost_per_mwh_usd: float


class OperationalKPIEngine:
    """
    Computes industry-standard operational KPIs for VPP assets.
    """

    def compute_availability(
        self,
        operational_hours: float,
        planned_outage_hours: float,
        forced_outage_hours: float,
        total_hours: float = 8760.0,
    ) -> Dict[str, float]:
        """
        Compute availability metrics per NERC GADS definitions.
        """
        available_hours = total_hours - planned_outage_hours - forced_outage_hours
        availability = available_hours / total_hours * 100.0

        forced_outage_rate = (
            forced_outage_hours / (operational_hours + forced_outage_hours) * 100.0
            if (operational_hours + forced_outage_hours) > 0 else 0.0
        )
        planned_factor = planned_outage_hours / total_hours * 100.0

        return {
            "availability_pct": round(availability, 2),
            "forced_outage_rate_pct": round(forced_outage_rate, 2),
            "planned_outage_rate_pct": round(planned_factor, 2),
            "operational_hours": operational_hours,
        }

    def compute_response_performance(
        self,
        dispatch_requests: int,
        successful_responses: int,
        response_times_s: List[float],
        target_response_s: float = 10.0,
    ) -> Dict[str, float]:
        """Compute dispatch response performance metrics."""
        success_rate = successful_responses / max(dispatch_requests, 1) * 100.0
        avg_rt = float(np.mean(response_times_s)) if response_times_s else 0.0
        pct_within_target = sum(1 for rt in response_times_s if rt <= target_response_s) / max(len(response_times_s), 1) * 100.0

        return {
            "success_rate_pct": round(success_rate, 2),
            "avg_response_time_s": round(avg_rt, 2),
            "pct_within_target_pct": round(pct_within_target, 2),
            "dispatch_requests": dispatch_requests,
        }

    def compute_reliability(
        self,
        failure_timestamps: List[float],
        repair_durations_h: List[float],
    ) -> Dict[str, float]:
        """Compute MTBF and MTTR."""
        if not failure_timestamps or len(failure_timestamps) < 2:
            return {"mtbf_h": float("inf"), "mttr_h": 0.0, "failure_count": 0}

        intervals = [
            failure_timestamps[i+1] - failure_timestamps[i] - repair_durations_h[i] * 3600
            for i in range(len(failure_timestamps) - 1)
        ]
        mtbf = float(np.mean(intervals)) / 3600.0  # Convert s to hours
        mttr = float(np.mean(repair_durations_h)) if repair_durations_h else 0.0

        return {
            "mtbf_h": round(mtbf, 1),
            "mttr_h": round(mttr, 2),
            "failure_count": len(failure_timestamps),
        }

    def fleet_kpi_summary(
        self, asset_kpis: List[AssetKPIs]
    ) -> Dict[str, float]:
        """Aggregate KPIs across the fleet."""
        if not asset_kpis:
            return {}
        return {
            "fleet_avg_availability_pct": float(np.mean([k.availability_pct for k in asset_kpis])),
            "fleet_capacity_factor_pct": float(np.mean([k.capacity_factor_pct for k in asset_kpis])),
            "fleet_response_success_pct": float(np.mean([k.response_success_rate_pct for k in asset_kpis])),
            "fleet_total_revenue_usd": float(sum(k.revenue_per_mw_usd for k in asset_kpis)),
            "worst_availability_asset": min(asset_kpis, key=lambda k: k.availability_pct).asset_id,
        }
