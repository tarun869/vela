"""Dataclasses for the m41 heuristic dispatch engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BindingConstraint = Literal[
    "CAPACITY_OBLIGATION",
    "THERMAL_LIMIT",
    "SOC_FLOOR",
    "DEGRADATION_COST",
]
ObligationState = Literal["COVERED", "AT_RISK", "BREACHED"]


@dataclass
class ObligationStatus:
    """Coverage status of a single commercial obligation for an interval."""

    obligation_id: str
    obligation_type: str
    committed_mw: float
    currently_covered_mw: float
    status: ObligationState
    risk_reason: str | None = None


@dataclass
class DispatchDecision:
    """A single asset's recommended action, with the explanation behind it."""

    asset_id: str
    recommended_mw: float  # positive=discharge, negative=charge, 0=hold
    reasoning: str
    binding_constraint: BindingConstraint | None
    constraint_cost_usd: float  # $ cost of honoring this constraint vs ignoring it
    unconstrained_mw: float  # what we would do with no constraints
    revenue_expected_usd: float


@dataclass
class FleetDispatchPlan:
    """The full, explainable dispatch plan for one 5-minute interval."""

    interval_start: str
    decisions: list[DispatchDecision] = field(default_factory=list)
    total_revenue_expected_usd: float = 0.0
    total_constraint_cost_usd: float = 0.0
    obligations_status: list[ObligationStatus] = field(default_factory=list)
    recommended_by: Literal["heuristic", "milp"] = "heuristic"


@dataclass
class SpikeAlert:
    """A real-time price-spike opportunity, raised outside the 5-min loop."""

    lmp: float
    prev_lmp: float
    pct_change: float
    recommended_action: str
    additional_revenue_usd: float
    obligation_risk: bool
