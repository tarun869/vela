"""Dataclasses for the m42 settlement and performance tracking module."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DispatchRecord:
    """Outcome of a single 5-minute dispatch interval."""

    timestamp: str
    asset_id: str
    dispatched_mw: float
    lmp_at_dispatch: float
    revenue_usd: float           # dispatched_mw * lmp * (5/60)
    degradation_cost_usd: float
    net_value_usd: float         # revenue - degradation_cost


@dataclass
class ObligationRecord:
    """Compliance result for one obligation delivery window."""

    obligation_id: str
    window_start: str
    window_end: str
    committed_mw: float
    delivered_mw: float
    compliant: bool
    penalty_usd: float           # 0 if compliant


@dataclass
class SettlementSummary:
    """End-of-day (or mid-day snapshot) P&L and compliance summary."""

    date: str
    total_revenue_usd: float
    total_degradation_cost_usd: float
    total_penalties_usd: float
    net_value_usd: float
    baseline_revenue_usd: float     # what simple threshold dispatch would have made
    outperformance_usd: float       # net_value - baseline_revenue
    outperformance_pct: float
    obligation_records: list[ObligationRecord] = field(default_factory=list)
    all_obligations_compliant: bool = True   # True iff zero penalties
    soh_delta_by_asset: dict[str, float] = field(default_factory=dict)
