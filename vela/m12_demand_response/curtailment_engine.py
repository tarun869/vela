"""
Load curtailment dispatch engine.

Determines optimal load shedding strategy across a fleet of controllable
loads, prioritizing by comfort impact, technology type, and contractual limits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np


class LoadType(str, Enum):
    HVAC = "hvac"
    EV_CHARGING = "ev_charging"
    INDUSTRIAL_PROCESS = "industrial_process"
    LIGHTING = "lighting"
    WATER_HEATER = "water_heater"
    POOL_PUMP = "pool_pump"
    REFRIGERATION = "refrigeration"


@dataclass
class ControllableLoad:
    load_id: str
    site_id: str
    load_type: LoadType
    current_kw: float               # Current consumption (kW)
    min_kw: float                   # Cannot curtail below this (kW)
    max_curtailment_kw: float       # Max reduction available (kW)
    curtailment_cost_usd_kwh: float # Site-specific cost of curtailment
    comfort_impact: float           # 0 (no impact) to 1 (high impact)
    max_duration_h: float = 4.0    # Maximum curtailment duration per event
    ramp_rate_kw_min: float = 10.0 # How fast load can be shed (kW/min)
    recovery_overshoot_factor: float = 1.15  # Rebound after curtailment


@dataclass
class CurtailmentAction:
    load_id: str
    site_id: str
    reduction_kw: float
    new_setpoint_kw: float
    estimated_cost_usd: float
    comfort_impact: float
    priority_score: float


@dataclass
class CurtailmentPlan:
    total_target_kw: float
    total_achievable_kw: float
    actions: List[CurtailmentAction]
    shortfall_kw: float
    plan_cost_usd: float
    avg_comfort_impact: float


class CurtailmentEngine:
    """
    Dispatches load curtailment to meet a demand reduction target.

    Strategy: greedy priority dispatch based on cost-adjusted comfort score.
    Loads are ranked by (curtailment_cost + comfort_impact_weight * comfort_impact).
    """

    def __init__(self, comfort_weight: float = 50.0) -> None:
        """
        Args:
            comfort_weight: Cost equivalent ($/kWh) for comfort impact, used in scoring.
        """
        self.comfort_weight = comfort_weight
        self._loads: Dict[str, ControllableLoad] = {}
        self._active_curtailments: Dict[str, CurtailmentAction] = {}

    def register_load(self, load: ControllableLoad) -> None:
        self._loads[load.load_id] = load

    def remove_load(self, load_id: str) -> None:
        self._loads.pop(load_id, None)

    def _priority_score(self, load: ControllableLoad) -> float:
        """
        Lower score = prefer to curtail first.
        Score = economic_cost + comfort_penalty.
        """
        return load.curtailment_cost_usd_kwh + self.comfort_weight * load.comfort_impact

    def plan_curtailment(
        self,
        target_kw: float,
        duration_h: float = 1.0,
        excluded_loads: Optional[List[str]] = None,
        site_filter: Optional[str] = None,
    ) -> CurtailmentPlan:
        """
        Generate optimal curtailment plan to achieve target reduction.

        Args:
            target_kw: Total demand reduction needed (kW).
            duration_h: Expected curtailment duration (hours).
            excluded_loads: Load IDs to exclude.
            site_filter: Restrict to a specific site.

        Returns:
            CurtailmentPlan with ordered actions.
        """
        excluded = set(excluded_loads or [])
        candidates = [
            l for l in self._loads.values()
            if l.load_id not in excluded
            and l.max_curtailment_kw > 0
            and duration_h <= l.max_duration_h
            and (site_filter is None or l.site_id == site_filter)
        ]

        # Sort by priority score (ascending — cheapest/least-impact first)
        candidates.sort(key=self._priority_score)

        actions: List[CurtailmentAction] = []
        remaining = target_kw
        total_cost = 0.0

        for load in candidates:
            if remaining <= 0:
                break
            reduction = min(remaining, load.max_curtailment_kw)
            new_setpoint = max(load.min_kw, load.current_kw - reduction)
            actual_reduction = load.current_kw - new_setpoint
            cost = actual_reduction * duration_h * load.curtailment_cost_usd_kwh

            action = CurtailmentAction(
                load_id=load.load_id,
                site_id=load.site_id,
                reduction_kw=actual_reduction,
                new_setpoint_kw=new_setpoint,
                estimated_cost_usd=cost,
                comfort_impact=load.comfort_impact,
                priority_score=self._priority_score(load),
            )
            actions.append(action)
            remaining -= actual_reduction
            total_cost += cost

        total_achieved = sum(a.reduction_kw for a in actions)
        avg_comfort = (
            sum(a.comfort_impact * a.reduction_kw for a in actions) / total_achieved
            if total_achieved > 0 else 0.0
        )

        return CurtailmentPlan(
            total_target_kw=target_kw,
            total_achievable_kw=total_achieved,
            actions=actions,
            shortfall_kw=max(0.0, target_kw - total_achieved),
            plan_cost_usd=total_cost,
            avg_comfort_impact=avg_comfort,
        )

    def execute_curtailment(self, plan: CurtailmentPlan) -> int:
        """
        Execute curtailment plan — store active curtailment state.

        Returns number of loads dispatched.
        """
        for action in plan.actions:
            self._active_curtailments[action.load_id] = action
            if action.load_id in self._loads:
                self._loads[action.load_id].current_kw = action.new_setpoint_kw
        return len(plan.actions)

    def restore_all(self) -> int:
        """Restore all curtailed loads to original setpoints."""
        for load_id, action in self._active_curtailments.items():
            if load_id in self._loads:
                original = action.new_setpoint_kw + action.reduction_kw
                # Apply recovery overshoot
                overshoot = original * self._loads[load_id].recovery_overshoot_factor
                self._loads[load_id].current_kw = overshoot
        n = len(self._active_curtailments)
        self._active_curtailments.clear()
        return n

    def rebound_forecast(self, plan: CurtailmentPlan, recovery_window_h: float = 2.0) -> float:
        """
        Estimate post-curtailment load rebound (MW surge).

        Uses recovery overshoot factors and curtailed load duration.
        """
        total_rebound = 0.0
        for action in plan.actions:
            load = self._loads.get(action.load_id)
            if load:
                rebound_extra = action.reduction_kw * (load.recovery_overshoot_factor - 1.0)
                total_rebound += rebound_extra
        return total_rebound

    def portfolio_flexibility(self) -> Dict[str, float]:
        """
        Report total available curtailment capacity by load type.

        Returns dict of load_type -> available_kw.
        """
        result: Dict[str, float] = {}
        for load in self._loads.values():
            result[load.load_type.value] = result.get(load.load_type.value, 0.0) + load.max_curtailment_kw
        return result
