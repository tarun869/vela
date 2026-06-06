"""
Power Purchase Agreement (PPA) financial modeling.

Models fixed-price and indexed PPA structures including settlement,
P90/P50 revenue analysis, and collateral requirements.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
import numpy as np


class PPAType(str, Enum):
    FIXED_PRICE = "fixed_price"
    INDEX_PLUS = "index_plus"          # Hub price + adder
    PROXY_REVENUE_SWAP = "proxy_revenue_swap"
    VIRTUAL = "virtual"                # VPPA (financial only)


@dataclass
class PPATerms:
    ppa_id: str
    ppa_type: PPAType
    counterparty_id: str
    start_date: str
    end_date: str
    contract_price_usd_mwh: float   # Strike price
    index_adder_usd_mwh: float = 0.0
    notional_mwh_year: float = 0.0
    curtailment_threshold_usd_mwh: float = 0.0  # PPA curtails if negative prices
    delivery_hub: str = "ERCOT_HUB_AVG"


@dataclass
class PPASettlement:
    period: str
    generated_mwh: float
    hub_price_usd_mwh: float
    contract_price_usd_mwh: float
    settlement_payment_usd: float   # + = buyer pays seller; - = seller pays buyer
    p50_revenue_usd: float
    p90_revenue_usd: float


class PPAModel:
    """
    Models PPA financial performance including settlement, P90, and NPV.
    """

    def __init__(self, terms: PPATerms) -> None:
        self.terms = terms

    def settle(self, generated_mwh: float, hub_price: float, period: str) -> PPASettlement:
        """
        Compute settlement for one period.

        VPPA settlement: (contract_price - hub_price) * notional
        Physical PPA: generator delivers at contract_price
        """
        terms = self.terms
        if terms.ppa_type == PPAType.VIRTUAL:
            # VPPA: purely financial — CFD settlement
            settlement = (terms.contract_price_usd_mwh - hub_price) * generated_mwh
        elif terms.ppa_type == PPAType.FIXED_PRICE:
            settlement = terms.contract_price_usd_mwh * generated_mwh
        elif terms.ppa_type == PPAType.INDEX_PLUS:
            effective_price = hub_price + terms.index_adder_usd_mwh
            settlement = effective_price * generated_mwh
        else:
            settlement = terms.contract_price_usd_mwh * generated_mwh

        return PPASettlement(
            period=period,
            generated_mwh=generated_mwh,
            hub_price_usd_mwh=hub_price,
            contract_price_usd_mwh=terms.contract_price_usd_mwh,
            settlement_payment_usd=settlement,
            p50_revenue_usd=settlement,
            p90_revenue_usd=settlement * 0.90,
        )

    def npv(
        self,
        annual_settlements: List[float],
        discount_rate: float = 0.08,
    ) -> float:
        """Compute NPV of PPA revenue stream."""
        return sum(
            s / (1 + discount_rate) ** (i + 1) for i, s in enumerate(annual_settlements)
        )

    def levelized_value(self, total_mwh: float, total_revenue_usd: float) -> float:
        """Levelized revenue per MWh over PPA term."""
        return total_revenue_usd / max(total_mwh, 1e-9)
