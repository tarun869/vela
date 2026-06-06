"""
Capacity contract modeling for resource adequacy commitments.

Models RA (Resource Adequacy) contracts, bilateral capacity trades,
and forward capacity market commitments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class CapacityContract:
    contract_id: str
    seller_id: str
    buyer_id: str
    capacity_mw: float
    price_usd_kw_month: float
    delivery_month: str
    resource_type: str         # "battery", "solar+storage", "demand_response"
    nqc_mw: float              # Net Qualifying Capacity (after derating)
    availability_guarantee_pct: float = 0.95


@dataclass
class CapacityEvent:
    event_id: str
    period: str
    called_mw: float
    delivered_mw: float
    penalty_threshold_pct: float = 0.90


@dataclass
class CapacitySettlement:
    contract_id: str
    period: str
    capacity_payment_usd: float
    performance_payment_usd: float
    penalty_usd: float
    net_payment_usd: float
    performance_pct: float


class CapacityContractEngine:
    """
    Manages capacity contract settlements and performance tracking.
    """

    def settle(
        self,
        contract: CapacityContract,
        events: List[CapacityEvent],
        period: str,
    ) -> CapacitySettlement:
        """
        Calculate capacity contract settlement.

        Performance below guarantee triggers penalty (typically 1.5x non-performance price).
        """
        base_payment = contract.nqc_mw * contract.price_usd_kw_month * 1000.0

        total_called = sum(e.called_mw for e in events)
        total_delivered = sum(e.delivered_mw for e in events)
        performance = total_delivered / max(total_called, 1.0) if total_called > 0 else 1.0

        # Performance payment / penalty
        if performance >= contract.availability_guarantee_pct:
            perf_payment = base_payment * 0.10  # Bonus for high availability
            penalty = 0.0
        else:
            shortfall_pct = contract.availability_guarantee_pct - performance
            penalty = base_payment * shortfall_pct * 1.5  # 1.5x shortfall penalty
            perf_payment = 0.0

        return CapacitySettlement(
            contract_id=contract.contract_id,
            period=period,
            capacity_payment_usd=base_payment,
            performance_payment_usd=perf_payment,
            penalty_usd=penalty,
            net_payment_usd=base_payment + perf_payment - penalty,
            performance_pct=performance,
        )

    def forward_ra_value(
        self,
        contract: CapacityContract,
        years: int = 1,
        discount_rate: float = 0.07,
    ) -> float:
        """NPV of capacity contract revenue stream."""
        monthly = contract.nqc_mw * contract.price_usd_kw_month * 1000.0
        total = sum(monthly / (1 + discount_rate / 12) ** m for m in range(1, years * 12 + 1))
        return total
