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
        scheduled_mwh: list[float] | None = None,
        metered_mwh: list[float] | None = None,
        lmp: list[float] | None = None,
        timestamps: list[datetime] | None = None,
        settlement_date: datetime | None = None,
        # Legacy positional-arg aliases kept for backwards compat
        scheduled: list[float] | None = None,
        metered: list[float] | None = None,
    ) -> SettlementStatement:
        """Calculate settlement for an asset.

        Accepts two calling conventions:
          1. engine.calculate(asset_id, scheduled_mwh=..., metered_mwh=..., lmp=..., settlement_date=...)
          2. engine.calculate(asset_id, scheduled, metered, lmp, timestamps)
        """
        # Resolve aliases
        _scheduled = scheduled_mwh if scheduled_mwh is not None else scheduled
        _metered   = metered_mwh   if metered_mwh   is not None else metered
        if _scheduled is None or _metered is None or lmp is None:
            raise ValueError("scheduled_mwh, metered_mwh, and lmp are required")

        n = len(_scheduled)
        if timestamps is None:
            # Build synthetic hourly timestamps from settlement_date
            if settlement_date is None:
                settlement_date = datetime.utcnow().replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            from datetime import timedelta
            timestamps = [settlement_date + timedelta(hours=i) for i in range(n)]

        assert len(_scheduled) == len(_metered) == len(lmp) == len(timestamps), (
            f"Length mismatch: scheduled={len(_scheduled)}, metered={len(_metered)}, "
            f"lmp={len(lmp)}, timestamps={len(timestamps)}"
        )
        intervals = [
            SettlementInterval(ts, s, m, p)
            for ts, s, m, p in zip(timestamps, _scheduled, _metered, lmp)
        ]
        _date = settlement_date or timestamps[0]
        stmt = SettlementStatement(asset_id, self.market, _date, intervals)
        logger.info(
            "Settlement for %s on %s: revenue=$%.2f, imbalance=$%.2f",
            asset_id, self.market, stmt.total_revenue, stmt.total_imbalance_charge,
        )
        return stmt
