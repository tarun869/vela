"""
Interconnection queue management and position analysis.

Tracks VPP project positions in ISO interconnection queues,
estimates upgrade costs, and forecasts commercial operation dates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class QueuePosition:
    queue_id: str
    project_id: str
    iso: str
    capacity_mw: float
    technology: str
    queue_date: str
    study_status: str     # "feasibility", "system_impact", "facilities", "executed"
    estimated_network_upgrade_usd: float
    estimated_cod: str    # Commercial operation date
    cluster_group: Optional[str] = None   # For cluster study ISOs (CAISO, MISO)


@dataclass
class QueueAnalysis:
    project_id: str
    queue_position_number: int
    total_ahead_capacity_mw: float   # Capacity from projects ahead in queue
    cost_update_factor: float        # Potential cost increase from cluster restudies
    estimated_withdrawal_risk_pct: float  # P(project withdraws) from industry stats
    revised_cost_usd: float


class InterconnectionQueueManager:
    """
    Tracks VPP portfolio across multiple ISO interconnection queues.
    """

    def __init__(self) -> None:
        self._queue: Dict[str, QueuePosition] = {}

    def add_project(self, position: QueuePosition) -> None:
        self._queue[position.project_id] = position

    def update_status(self, project_id: str, new_status: str) -> None:
        if project_id in self._queue:
            self._queue[project_id].study_status = new_status

    def analyze_position(self, project_id: str) -> Optional[QueueAnalysis]:
        """
        Analyze queue position risk and cost exposure.

        Industry data: ~50% of queued projects eventually withdraw.
        Projects late in a cluster see 2-5x cost increases on restudies.
        """
        pos = self._queue.get(project_id)
        if not pos:
            return None

        # Count projects ahead in same ISO
        iso_projects = sorted(
            [p for p in self._queue.values() if p.iso == pos.iso],
            key=lambda p: p.queue_date,
        )
        idx = next((i for i, p in enumerate(iso_projects) if p.project_id == project_id), 0)
        ahead_capacity = sum(p.capacity_mw for p in iso_projects[:idx])

        # Withdrawal risk increases with queue length (empirical)
        withdrawal_risk = min(0.6, 0.15 + idx * 0.05)

        # Cost update: cluster restudy can 2-3x estimates for late entrants
        cost_factor = 1.0 + max(0.0, (idx - 5) * 0.2)
        revised_cost = pos.estimated_network_upgrade_usd * cost_factor

        return QueueAnalysis(
            project_id=project_id,
            queue_position_number=idx + 1,
            total_ahead_capacity_mw=ahead_capacity,
            cost_update_factor=cost_factor,
            estimated_withdrawal_risk_pct=withdrawal_risk * 100,
            revised_cost_usd=revised_cost,
        )

    def portfolio_summary(self) -> Dict[str, int]:
        by_status: Dict[str, int] = {}
        for pos in self._queue.values():
            by_status[pos.study_status] = by_status.get(pos.study_status, 0) + 1
        return by_status
