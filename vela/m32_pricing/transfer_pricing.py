"""
Transfer pricing for VPP intra-company energy transactions.

Models arm's-length pricing for inter-entity energy transfers within
a VPP operating entity structure, ensuring tax compliance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class EntityProfile:
    entity_id: str
    name: str
    jurisdiction: str
    tax_rate: float         # Effective corporate tax rate
    functional_profile: str # "generator", "aggregator", "offtaker"


@dataclass
class IntraGroupTransfer:
    transfer_id: str
    seller_entity: str
    buyer_entity: str
    energy_mwh: float
    transfer_price_usd_mwh: float
    market_reference_price: float   # Arm's-length benchmark
    transfer_period: str


@dataclass
class TransferPricingAnalysis:
    transfer_id: str
    arm_length_range: Tuple[float, float]   # IQR of comparable transactions
    is_within_range: bool
    adjustment_needed_usd: float
    tax_exposure_usd: float


class TransferPricingEngine:
    """
    Evaluates VPP intra-group transfer prices for tax compliance.

    Uses comparable uncontrolled price (CUP) method as primary
    method (OECD Transfer Pricing Guidelines).
    """

    def __init__(self) -> None:
        self._entities: Dict[str, EntityProfile] = {}

    def register_entity(self, entity: EntityProfile) -> None:
        self._entities[entity.entity_id] = entity

    def arm_length_range(
        self,
        market_price: float,
        comparable_transactions: Optional[List[float]] = None,
    ) -> Tuple[float, float]:
        """
        Compute arm's-length range (interquartile range of comparables).

        If no comparables provided, uses ±20% of market reference price.
        """
        if comparable_transactions and len(comparable_transactions) >= 4:
            arr = np.array(comparable_transactions)
            q1 = float(np.percentile(arr, 25))
            q3 = float(np.percentile(arr, 75))
            return (q1, q3)
        return (market_price * 0.80, market_price * 1.20)

    def analyze(
        self,
        transfer: IntraGroupTransfer,
        comparable_transactions: Optional[List[float]] = None,
    ) -> TransferPricingAnalysis:
        """Assess whether a transfer price is at arm's length."""
        lo, hi = self.arm_length_range(transfer.market_reference_price, comparable_transactions)
        in_range = lo <= transfer.transfer_price_usd_mwh <= hi

        # If outside range, compute required adjustment
        if transfer.transfer_price_usd_mwh < lo:
            adjustment_per_mwh = lo - transfer.transfer_price_usd_mwh
        elif transfer.transfer_price_usd_mwh > hi:
            adjustment_per_mwh = transfer.transfer_price_usd_mwh - hi
        else:
            adjustment_per_mwh = 0.0

        adjustment = adjustment_per_mwh * transfer.energy_mwh

        # Tax exposure: adjustment * max tax rate differential
        seller = self._entities.get(transfer.seller_entity)
        buyer = self._entities.get(transfer.buyer_entity)
        max_rate = max(
            getattr(seller, "tax_rate", 0.25),
            getattr(buyer, "tax_rate", 0.25),
        )
        tax_exposure = adjustment * max_rate

        return TransferPricingAnalysis(
            transfer_id=transfer.transfer_id,
            arm_length_range=(lo, hi),
            is_within_range=in_range,
            adjustment_needed_usd=adjustment,
            tax_exposure_usd=tax_exposure,
        )
