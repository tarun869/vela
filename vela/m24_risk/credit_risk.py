"""
Counterparty credit risk for VPP bilateral contracts and ISO exposure.

Covers expected exposure, credit valuation adjustment (CVA),
and credit limit management for energy trading counterparties.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class Counterparty:
    party_id: str
    name: str
    credit_rating: str         # "AAA", "BBB", "BB", etc.
    pd_annual: float           # Annual probability of default (0–1)
    lgd: float = 0.40          # Loss given default (40% typical for unsecured)
    credit_limit_usd: float = 1_000_000.0


@dataclass
class CreditExposure:
    counterparty_id: str
    current_exposure_usd: float       # Mark-to-market exposure
    potential_future_exposure_usd: float   # 95th percentile future exposure
    expected_exposure_usd: float
    credit_value_adjustment_usd: float   # CVA = integral of PD * LGD * EE * discount
    within_limit: bool


# Investment-grade PD mapping (Moody's historical)
RATING_PD_MAP: Dict[str, float] = {
    "AAA": 0.0002,
    "AA": 0.0003,
    "A": 0.0006,
    "BBB": 0.002,
    "BB": 0.012,
    "B": 0.05,
    "CCC": 0.20,
}


class CreditRiskEngine:
    """
    Manages counterparty credit risk for VPP trading book.
    """

    def __init__(self, recovery_rate: float = 0.40) -> None:
        self.recovery_rate = recovery_rate
        self._counterparties: Dict[str, Counterparty] = {}

    def register_counterparty(self, cp: Counterparty) -> None:
        self._counterparties[cp.party_id] = cp

    def compute_exposure(
        self,
        counterparty_id: str,
        contract_mtm_usd: float,
        maturity_years: float,
        volatility_pct: float = 0.30,
    ) -> CreditExposure:
        """
        Compute credit exposure metrics for a bilateral contract.

        PFE (95th percentile) = current_exposure * exp(z_95 * vol * sqrt(T))
        CVA ≈ PD * LGD * EE * discount_factor (simplified one-period)
        """
        cp = self._counterparties[counterparty_id]
        current = max(0.0, contract_mtm_usd)  # Only at-risk when in-the-money
        z_95 = 1.645
        pfe = current * np.exp(z_95 * volatility_pct * np.sqrt(maturity_years))
        ee = current * (1 + volatility_pct * np.sqrt(maturity_years))  # Simplified

        pd = RATING_PD_MAP.get(cp.credit_rating, 0.05)
        discount = np.exp(-0.03 * maturity_years)  # 3% risk-free rate
        cva = pd * cp.lgd * ee * discount

        return CreditExposure(
            counterparty_id=counterparty_id,
            current_exposure_usd=current,
            potential_future_exposure_usd=pfe,
            expected_exposure_usd=ee,
            credit_value_adjustment_usd=cva,
            within_limit=pfe <= cp.credit_limit_usd,
        )

    def portfolio_cva(self, exposures: List[CreditExposure]) -> float:
        """Total CVA for portfolio (assumes independence across counterparties)."""
        return sum(e.credit_value_adjustment_usd for e in exposures)
