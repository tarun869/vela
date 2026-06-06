"""
Predictive maintenance planning for VPP assets.

Schedules maintenance windows based on asset health scores,
manufacturer recommendations, and market price forecasts to
minimize revenue impact while maintaining reliability.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class MaintenanceTask:
    task_id: str
    asset_id: str
    task_type: str          # "preventive", "predictive", "corrective"
    estimated_duration_h: float
    required_crew: int
    parts_cost_usd: float
    labor_cost_usd: float
    urgency_score: float    # 0–1 (1 = must do immediately)
    deadline: Optional[str] = None


@dataclass
class MaintenanceWindow:
    window_id: str
    asset_id: str
    start_hour: int         # Hour of week (0–167)
    duration_h: float
    opportunity_cost_usd: float   # Lost revenue during outage
    total_cost_usd: float
    tasks: List[str]        # task_ids scheduled in this window


@dataclass
class MaintenancePlan:
    plan_id: str
    windows: List[MaintenanceWindow]
    total_outage_h: float
    total_cost_usd: float
    coverage_pct: float     # Fraction of tasks scheduled


class MaintenancePlanner:
    """
    Optimizes maintenance scheduling to minimize revenue impact.

    Approach:
    1. Score hours by expected revenue (use hourly price forecast).
    2. Schedule tasks during lowest-revenue windows.
    3. Group tasks for the same asset to minimize total outage events.
    """

    def __init__(self, price_forecast_usd_mwh: Optional[List[float]] = None) -> None:
        """
        Args:
            price_forecast_usd_mwh: 168-hour (1-week) price forecast.
        """
        if price_forecast_usd_mwh is None:
            # Default: flat $40/MWh with weekday/weekend pattern
            prices = [40.0] * 168
            for h in range(168):
                hour = h % 24
                if 8 <= hour <= 20:
                    prices[h] *= 1.5
                if h // 24 in (5, 6):  # weekend
                    prices[h] *= 0.8
            self.prices = prices
        else:
            self.prices = price_forecast_usd_mwh

    def score_windows(self, asset_capacity_mw: float) -> List[Tuple[int, float]]:
        """
        Score each hour as maintenance opportunity.

        Lower score = better time to take outage.
        Returns sorted list of (hour, opportunity_cost_usd).
        """
        scored = []
        for h, price in enumerate(self.prices):
            cost = price * asset_capacity_mw  # Revenue lost per hour
            scored.append((h, cost))
        return sorted(scored, key=lambda x: x[1])

    def plan(
        self,
        tasks: List[MaintenanceTask],
        asset_capacity_mw: float,
    ) -> MaintenancePlan:
        """
        Build optimal maintenance plan for a list of tasks.
        """
        import uuid
        scored = self.score_windows(asset_capacity_mw)

        # Group tasks by asset
        by_asset: Dict[str, List[MaintenanceTask]] = {}
        for t in tasks:
            by_asset.setdefault(t.asset_id, []).append(t)

        windows: List[MaintenanceWindow] = []
        hour_ptr = 0

        for asset_id, asset_tasks in by_asset.items():
            total_duration = sum(t.estimated_duration_h for t in asset_tasks)
            total_cost = sum(t.parts_cost_usd + t.labor_cost_usd for t in asset_tasks)

            if hour_ptr < len(scored):
                best_hour, opp_cost = scored[hour_ptr]
                hour_ptr += 1
            else:
                best_hour, opp_cost = 0, 0.0

            windows.append(MaintenanceWindow(
                window_id=str(uuid.uuid4())[:8],
                asset_id=asset_id,
                start_hour=best_hour,
                duration_h=total_duration,
                opportunity_cost_usd=opp_cost * total_duration,
                total_cost_usd=total_cost + opp_cost * total_duration,
                tasks=[t.task_id for t in asset_tasks],
            ))

        total_outage = sum(w.duration_h for w in windows)
        total_cost = sum(w.total_cost_usd for w in windows)
        scheduled_tasks = sum(len(w.tasks) for w in windows)

        return MaintenancePlan(
            plan_id=str(uuid.uuid4())[:8],
            windows=windows,
            total_outage_h=total_outage,
            total_cost_usd=total_cost,
            coverage_pct=scheduled_tasks / max(len(tasks), 1),
        )
