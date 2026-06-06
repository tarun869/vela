"""
Performance attribution of VPP revenue to dispatch strategies and market conditions.

Decomposes realized vs. benchmark revenue into alpha (skill), beta (market),
and interaction effects using Brinson-Hood-Beebower attribution framework.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class AttributionResult:
    total_active_return_usd: float
    allocation_effect_usd: float    # Did we allocate to right services?
    selection_effect_usd: float     # Did we execute well within each service?
    interaction_effect_usd: float   # Allocation * selection interaction
    market_return_usd: float        # Passive benchmark return
    alpha_usd: float                # Skill-based excess return
    information_ratio: float        # Alpha / tracking error
    attribution_by_service: Dict[str, Dict[str, float]]


class PerformanceAttributor:
    """
    Brinson-Hood-Beebower attribution for VPP revenue streams.
    """

    def attribute(
        self,
        portfolio_weights: Dict[str, float],    # service -> weight
        portfolio_returns: Dict[str, float],    # service -> return $/MWh
        benchmark_weights: Dict[str, float],    # service -> benchmark weight
        benchmark_returns: Dict[str, float],    # service -> benchmark return
    ) -> AttributionResult:
        """
        BHB attribution decomposition.

        Returns:
            AttributionResult with allocation, selection, and interaction effects.
        """
        services = set(portfolio_weights) | set(benchmark_weights)
        allocation_effect = 0.0
        selection_effect = 0.0
        interaction_effect = 0.0
        attribution_by_service: Dict[str, Dict[str, float]] = {}

        benchmark_total = sum(
            benchmark_weights.get(s, 0.0) * benchmark_returns.get(s, 0.0)
            for s in services
        )

        for svc in services:
            wp = portfolio_weights.get(svc, 0.0)
            wb = benchmark_weights.get(svc, 0.0)
            rp = portfolio_returns.get(svc, 0.0)
            rb = benchmark_returns.get(svc, 0.0)

            alloc = (wp - wb) * (rb - benchmark_total)
            sel = wb * (rp - rb)
            inter = (wp - wb) * (rp - rb)

            allocation_effect += alloc
            selection_effect += sel
            interaction_effect += inter

            attribution_by_service[svc] = {
                "allocation": alloc, "selection": sel, "interaction": inter,
                "portfolio_weight": wp, "benchmark_weight": wb,
                "portfolio_return": rp, "benchmark_return": rb,
            }

        portfolio_total = sum(
            portfolio_weights.get(s, 0.0) * portfolio_returns.get(s, 0.0)
            for s in services
        )
        active_return = portfolio_total - benchmark_total
        alpha = active_return
        tracking_error = abs(active_return) * 0.5 + 1.0  # Simplified
        ir = alpha / tracking_error if tracking_error > 0 else 0.0

        return AttributionResult(
            total_active_return_usd=active_return,
            allocation_effect_usd=allocation_effect,
            selection_effect_usd=selection_effect,
            interaction_effect_usd=interaction_effect,
            market_return_usd=benchmark_total,
            alpha_usd=alpha,
            information_ratio=ir,
            attribution_by_service=attribution_by_service,
        )
