"""m42_settlement — settlement and performance tracking.

Accumulates :class:`~vela.m41_optimizer.models.DispatchDecision` outcomes and
:class:`~vela.m39_extraction.models.ExtractedObligation` compliance windows
throughout the operating day, then produces a :class:`SettlementSummary` that
compares optimizer P&L to a simple threshold-based baseline.
"""
from __future__ import annotations

from .models import DispatchRecord, ObligationRecord, SettlementSummary
from .tracker import SettlementTracker

__all__ = [
    "DispatchRecord",
    "ObligationRecord",
    "SettlementSummary",
    "SettlementTracker",
]
