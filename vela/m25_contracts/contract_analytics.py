"""
Contract portfolio analytics for VPP financial management.

Provides portfolio-level P&L attribution, contract value-at-risk,
and mark-to-market analytics across all contract types.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import numpy as np


@dataclass
class ContractSummary:
    contract_id: str
    contract_type: str
    counterparty: str
    notional_mwh: float
    mark_to_market_usd: float
    unrealized_pnl_usd: float
    realized_pnl_usd: float
    days_remaining: int
    credit_exposure_usd: float


@dataclass
class PortfolioAnalytics:
    total_notional_mwh: float
    total_mtm_usd: float
    unrealized_pnl_usd: float
    realized_pnl_usd: float
    var_95_usd: float
    concentration_by_type: Dict[str, float]
    concentration_by_counterparty: Dict[str, float]
    hedge_ratio: float


class ContractAnalyticsEngine:
    """
    Computes portfolio-level analytics across all VPP contracts.
    """

    def __init__(self) -> None:
        self._contracts: List[ContractSummary] = []

    def add(self, summary: ContractSummary) -> None:
        self._contracts.append(summary)

    def portfolio_analytics(self) -> PortfolioAnalytics:
        """Compute portfolio-level aggregated metrics."""
        contracts = self._contracts

        total_notional = sum(c.notional_mwh for c in contracts)
        total_mtm = sum(c.mark_to_market_usd for c in contracts)
        total_unrealized = sum(c.unrealized_pnl_usd for c in contracts)
        total_realized = sum(c.realized_pnl_usd for c in contracts)

        # VaR (simplified 95% percentile from MTM distribution)
        mtm_values = np.array([c.mark_to_market_usd for c in contracts])
        var_95 = float(np.percentile(np.abs(mtm_values), 95)) if len(mtm_values) > 0 else 0.0

        # Concentration by type
        by_type: Dict[str, float] = {}
        for c in contracts:
            by_type[c.contract_type] = by_type.get(c.contract_type, 0.0) + c.notional_mwh

        # Concentration by counterparty
        by_cp: Dict[str, float] = {}
        for c in contracts:
            by_cp[c.counterparty] = by_cp.get(c.counterparty, 0.0) + c.notional_mwh

        # Hedge ratio: fixed-price contracts / total notional
        fixed_notional = sum(
            c.notional_mwh for c in contracts if "ppa" in c.contract_type or "fixed" in c.contract_type
        )
        hedge_ratio = fixed_notional / max(total_notional, 1.0)

        return PortfolioAnalytics(
            total_notional_mwh=total_notional,
            total_mtm_usd=total_mtm,
            unrealized_pnl_usd=total_unrealized,
            realized_pnl_usd=total_realized,
            var_95_usd=var_95,
            concentration_by_type=by_type,
            concentration_by_counterparty=by_cp,
            hedge_ratio=hedge_ratio,
        )

    def pnl_attribution(self) -> Dict[str, float]:
        """Decompose P&L by contract type."""
        result: Dict[str, float] = {}
        for c in self._contracts:
            key = c.contract_type
            result[key] = result.get(key, 0.0) + c.realized_pnl_usd + c.unrealized_pnl_usd
        return result
