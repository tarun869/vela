"""
Risk limits framework for VPP trading and operations.

Implements hierarchical risk limit structure with real-time monitoring,
limit breach detection, and escalation workflows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional


class LimitType(str, Enum):
    VAR = "var"
    NOTIONAL = "notional"
    CONCENTRATION = "concentration"
    DRAWDOWN = "drawdown"
    CREDIT = "credit"


class LimitStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"       # 80% of limit
    BREACH = "breach"         # 100% of limit
    HARD_BREACH = "hard_breach"  # 110% of limit — immediate action required


@dataclass
class RiskLimit:
    limit_id: str
    limit_type: LimitType
    description: str
    soft_limit: float     # Warning threshold
    hard_limit: float     # Breach threshold
    owner: str            # Trader/desk responsible
    escalation_contact: str


@dataclass
class LimitCheck:
    limit_id: str
    current_value: float
    soft_limit: float
    hard_limit: float
    status: LimitStatus
    utilization_pct: float
    breach_amount: float


class RiskLimitMonitor:
    """
    Real-time risk limit monitoring with callback-based escalation.
    """

    def __init__(self) -> None:
        self._limits: Dict[str, RiskLimit] = {}
        self._escalation_callbacks: List[Callable[[LimitCheck], None]] = []

    def add_limit(self, limit: RiskLimit) -> None:
        self._limits[limit.limit_id] = limit

    def on_breach(self, callback: Callable[[LimitCheck], None]) -> None:
        self._escalation_callbacks.append(callback)

    def check(self, limit_id: str, current_value: float) -> LimitCheck:
        """Check a single limit and trigger callbacks if breached."""
        limit = self._limits[limit_id]
        utilization = current_value / max(limit.hard_limit, 1e-9)

        if current_value >= limit.hard_limit * 1.10:
            status = LimitStatus.HARD_BREACH
        elif current_value >= limit.hard_limit:
            status = LimitStatus.BREACH
        elif current_value >= limit.soft_limit:
            status = LimitStatus.WARNING
        else:
            status = LimitStatus.OK

        breach_amount = max(0.0, current_value - limit.hard_limit)

        result = LimitCheck(
            limit_id=limit_id,
            current_value=current_value,
            soft_limit=limit.soft_limit,
            hard_limit=limit.hard_limit,
            status=status,
            utilization_pct=utilization * 100,
            breach_amount=breach_amount,
        )

        if status in (LimitStatus.BREACH, LimitStatus.HARD_BREACH):
            for cb in self._escalation_callbacks:
                try:
                    cb(result)
                except Exception:
                    pass

        return result

    def check_all(self, current_values: Dict[str, float]) -> List[LimitCheck]:
        """Check all registered limits."""
        return [self.check(lid, val) for lid, val in current_values.items() if lid in self._limits]

    def summary_dashboard(self, current_values: Dict[str, float]) -> Dict[str, str]:
        """Return color-coded summary for dashboard display."""
        results = self.check_all(current_values)
        return {r.limit_id: r.status.value for r in results}
