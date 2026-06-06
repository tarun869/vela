"""Revenue sharing calculations for multi-owner VPP portfolios."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class RevenueShareAgreement:
    """
    Defines how revenue from an asset is split between the asset owner and the VPP operator.
    """
    agreement_id: str
    asset_id: str
    owner_id: str
    vpp_operator_id: str
    structure: Literal["fixed_split", "tiered", "performance_bonus"] = "fixed_split"
    # Fixed split: owner receives `owner_share_pct` of net revenue
    owner_share_pct: float = 0.80  # 80% to owner, 20% to operator
    # Minimum guaranteed payment (USD/month) to owner regardless of performance
    minimum_guarantee_usd: float = 0.0
    # Performance bonus: owner gets extra % if efficiency > threshold
    bonus_threshold_pct: float = 0.90  # 90% dispatch compliance
    bonus_additional_pct: float = 0.05  # +5% bonus
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    def is_active(self, as_of: datetime | None = None) -> bool:
        from datetime import timezone
        now = as_of or datetime.now(timezone.utc)
        if self.effective_from and now < self.effective_from:
            return False
        if self.effective_to and now > self.effective_to:
            return False
        return True


@dataclass
class RevenueAllocation:
    """Result of a revenue share calculation for one period."""
    asset_id: str
    period_start: datetime
    period_end: datetime
    gross_revenue_usd: float
    platform_fees_usd: float
    net_revenue_usd: float
    owner_share_usd: float
    operator_share_usd: float
    bonus_usd: float
    minimum_guarantee_applied: bool


class RevenueShareCalculator:
    """
    Calculates revenue allocations for all assets in a portfolio
    given their share agreements and gross revenue for a period.
    """

    def __init__(self, agreements: list[RevenueShareAgreement]) -> None:
        self.agreements = {a.asset_id: a for a in agreements}

    def calculate(
        self,
        asset_id: str,
        period_start: datetime,
        period_end: datetime,
        gross_revenue_usd: float,
        platform_fee_pct: float = 0.02,
        dispatch_compliance_pct: float = 1.0,
    ) -> RevenueAllocation:
        """
        Calculate owner and operator shares for one asset for one settlement period.

        platform_fee_pct: fee taken off the top before the split (default 2%)
        dispatch_compliance_pct: fraction of requested dispatch actually delivered (0-1)
        """
        agreement = self.agreements.get(asset_id)
        if agreement is None:
            # Default split: 80/20 if no agreement on file
            agreement = RevenueShareAgreement(
                agreement_id="default",
                asset_id=asset_id,
                owner_id="unknown",
                vpp_operator_id="vela",
            )
            logger.warning("No revenue share agreement found for asset=%s; using default 80/20", asset_id)

        platform_fee = round(gross_revenue_usd * platform_fee_pct, 4)
        net = round(gross_revenue_usd - platform_fee, 4)

        owner_pct = agreement.owner_share_pct
        bonus = 0.0
        if (
            agreement.structure == "performance_bonus"
            and dispatch_compliance_pct >= agreement.bonus_threshold_pct
        ):
            bonus = round(net * agreement.bonus_additional_pct, 4)
            owner_pct = min(1.0, owner_pct + agreement.bonus_additional_pct)

        owner_share = round(net * owner_pct + bonus, 4)
        operator_share = round(net - owner_share + bonus, 4)

        # Apply minimum guarantee
        min_applied = False
        if owner_share < agreement.minimum_guarantee_usd:
            shortfall = agreement.minimum_guarantee_usd - owner_share
            owner_share = agreement.minimum_guarantee_usd
            operator_share = max(0.0, operator_share - shortfall)
            min_applied = True

        return RevenueAllocation(
            asset_id=asset_id,
            period_start=period_start,
            period_end=period_end,
            gross_revenue_usd=gross_revenue_usd,
            platform_fees_usd=platform_fee,
            net_revenue_usd=net,
            owner_share_usd=owner_share,
            operator_share_usd=operator_share,
            bonus_usd=bonus,
            minimum_guarantee_applied=min_applied,
        )

    def calculate_portfolio(
        self,
        revenues: dict[str, float],  # {asset_id: gross_revenue_usd}
        period_start: datetime,
        period_end: datetime,
        platform_fee_pct: float = 0.02,
    ) -> list[RevenueAllocation]:
        return [
            self.calculate(asset_id, period_start, period_end, gross, platform_fee_pct)
            for asset_id, gross in revenues.items()
        ]
