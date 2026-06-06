"""Settlement engine — reconciles scheduled vs metered energy."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SettlementInterval:
    interval_start: datetime
    scheduled_mwh: float
    metered_mwh: float
    lmp: float
    imbalance_charge: float = 0.0
    revenue: float = 0.0

    def __post_init__(self) -> None:
        imbalance = self.metered_mwh - self.scheduled_mwh
        self.imbalance_charge = abs(imbalance) * self.lmp * 0.1
        self.revenue = self.metered_mwh * self.lmp - self.imbalance_charge


@dataclass
class SettlementStatement:
    asset_id: str
    market: str
    settlement_date: datetime
    intervals: list[SettlementInterval] = field(default_factory=list)

    @property
    def total_revenue(self) -> float:
        return sum(i.revenue for i in self.intervals)

    @property
    def total_imbalance_charge(self) -> float:
        return sum(i.imbalance_charge for i in self.intervals)

    @property
    def total_energy_mwh(self) -> float:
        return sum(i.metered_mwh for i in self.intervals)


class SettlementEngine:
    def __init__(self, market: str) -> None:
        self.market = market

    def calculate(
        self,
        asset_id: str,
        scheduled: list[float],
        metered: list[float],
        lmp: list[float],
        timestamps: list[datetime],
    ) -> SettlementStatement:
        assert len(scheduled) == len(metered) == len(lmp) == len(timestamps)
        intervals = [
            SettlementInterval(ts, s, m, p)
            for ts, s, m, p in zip(timestamps, scheduled, metered, lmp)
        ]
        stmt = SettlementStatement(asset_id, self.market, timestamps[0], intervals)
        logger.info(
            "Settlement for %s on %s: revenue=$%.2f, imbalance=$%.2f",
            asset_id, self.market, stmt.total_revenue, stmt.total_imbalance_charge,
        )
        return stmt
