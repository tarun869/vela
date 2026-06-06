"""
Interconnection agreement modeling and cost tracking.

Covers FERC Order 2003/2006 Large Generator Interconnection Agreement (LGIA)
and Small Generator Interconnection Agreement (SGIA) processes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
import numpy as np


class InterconnectionStage(str, Enum):
    APPLICATION = "application"
    FEASIBILITY_STUDY = "feasibility_study"
    SYSTEM_IMPACT_STUDY = "system_impact_study"
    FACILITIES_STUDY = "facilities_study"
    AGREEMENT_EXECUTION = "agreement_execution"
    CONSTRUCTION = "construction"
    COMMERCIAL_OPERATION = "commercial_operation"


@dataclass
class InterconnectionRequest:
    project_id: str
    applicant_id: str
    capacity_mw: float
    interconnection_voltage_kv: float
    point_of_interconnection: str
    fuel_type: str
    commercial_operation_date: str
    study_deposits_usd: float = 0.0
    network_upgrade_cost_usd: float = 0.0
    customer_facilities_cost_usd: float = 0.0


@dataclass
class InterconnectionMilestone:
    stage: InterconnectionStage
    planned_date: str
    actual_date: Optional[str]
    cost_incurred_usd: float
    issues: List[str]

    @property
    def complete(self) -> bool:
        return self.actual_date is not None


class InterconnectionTracker:
    """
    Tracks interconnection queue position, study progress, and cost evolution.
    """

    def __init__(self) -> None:
        self._projects: Dict[str, InterconnectionRequest] = {}
        self._milestones: Dict[str, List[InterconnectionMilestone]] = {}

    def register(self, request: InterconnectionRequest) -> None:
        self._projects[request.project_id] = request
        self._milestones[request.project_id] = []

    def add_milestone(self, project_id: str, milestone: InterconnectionMilestone) -> None:
        self._milestones.setdefault(project_id, []).append(milestone)

    def current_stage(self, project_id: str) -> Optional[InterconnectionStage]:
        """Return the current (last incomplete or last completed) stage."""
        milestones = self._milestones.get(project_id, [])
        completed = [m for m in milestones if m.complete]
        if completed:
            return completed[-1].stage
        return InterconnectionStage.APPLICATION

    def total_cost(self, project_id: str) -> float:
        req = self._projects[project_id]
        spent = sum(m.cost_incurred_usd for m in self._milestones.get(project_id, []))
        return req.study_deposits_usd + req.network_upgrade_cost_usd + req.customer_facilities_cost_usd + spent

    def schedule_delay_days(self, project_id: str) -> int:
        """Count total schedule slippage days across completed milestones."""
        from datetime import datetime
        total = 0
        for m in self._milestones.get(project_id, []):
            if m.actual_date and m.planned_date:
                planned = datetime.strptime(m.planned_date, "%Y-%m-%d")
                actual = datetime.strptime(m.actual_date, "%Y-%m-%d")
                delay = (actual - planned).days
                total += max(0, delay)
        return total
