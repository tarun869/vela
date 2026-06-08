"""Abstract dispatch-optimizer interface.

Lets a future MILP optimizer be swapped in for :class:`HeuristicOptimizer`
without touching the scheduler or API layers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from vela.m39_extraction.models import ExtractedObligation

from .models import FleetDispatchPlan


class DispatchOptimizer(ABC):
    """Produces an explainable :class:`FleetDispatchPlan` from current state."""

    @abstractmethod
    async def optimize(
        self,
        fleet_state: dict[str, Any],
        current_lmp: float,
        obligations: Sequence[ExtractedObligation],
        current_hour: int,
    ) -> FleetDispatchPlan:
        """Return a dispatch plan for the upcoming interval."""
