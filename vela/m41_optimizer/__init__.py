"""m41_optimizer — heuristic, fully-explainable dispatch engine (demo-grade).

Every 5 minutes it reads fleet state + LMP + active obligations and produces a
:class:`FleetDispatchPlan` where each asset decision names its binding constraint
and the dollar cost of honoring it. Sits behind :class:`DispatchOptimizer` so a
MILP optimizer can be swapped in later.
"""
from __future__ import annotations

from .heuristic import HeuristicOptimizer, detect_spike
from .interface import DispatchOptimizer
from .models import (
    DispatchDecision,
    FleetDispatchPlan,
    ObligationStatus,
    SpikeAlert,
)
from .scheduler import DispatchScheduler

__all__ = [
    "DispatchOptimizer",
    "HeuristicOptimizer",
    "detect_spike",
    "DispatchScheduler",
    "DispatchDecision",
    "FleetDispatchPlan",
    "ObligationStatus",
    "SpikeAlert",
]
