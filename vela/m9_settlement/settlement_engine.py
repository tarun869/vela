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
        settlement_date_or_scheduled: "datetime | list[float] | None" = None,
        scheduled_or_metered: "list[float] | None" = None,
        metered_or_lmp: "list[float] | None" = None,
        lmp_or_timestamps: "list[float] | list[datetime] | None" = None,
        *,
        scheduled_mwh: "list[float] | None" = None,
        metered_mwh: "list[float] | None" = None,
        lmp: "list[float] | None" = None,
        timestamps: "list[datetime] | None" = None,
        settlement_date: "datetime | None" = None,
    ) -> "SettlementStatement":
        """Calculate settlement for an asset.

        Accepts multiple calling conventions:
          1. Keyword-only:
             engine.calculate(asset_id,
                              scheduled_mwh=..., metered_mwh=..., lmp=...,
                              settlement_date=...)
          2. Legacy positional (5 args):
             engine.calculate(asset_id, settlement_date, scheduled, metered, lmp)
          3. Legacy positional (4 args, no settlement_date):
             engine.calculate(asset_id, scheduled, metered, lmp, timestamps)
        """
        from datetime import timedelta as _td

        # --- Detect calling convention ---
        arg1 = settlement_date_or_scheduled
        arg2 = scheduled_or_metered
        arg3 = metered_or_lmp
        arg4 = lmp_or_timestamps

        if isinstance(arg1, datetime):
            # Convention 2: (asset_id, settlement_date, scheduled, metered, lmp)
            _date = arg1
            _scheduled = arg2
            _metered   = arg3
            _lmp       = arg4
        elif isinstance(arg1, list):
            # Convention 3: (asset_id, scheduled, metered, lmp, timestamps)
            _scheduled = arg1
            _metered   = arg2
            _lmp       = arg3
            if isinstance(arg4, list) and arg4 and isinstance(arg4[0], datetime):
                timestamps = arg4
            _date = settlement_date
        else:
            # Convention 1: all kwargs
            _scheduled = scheduled_mwh
            _metered   = metered_mwh
            _lmp       = lmp
            _date      = settlement_date

        if _scheduled is None or _metered is None or _lmp is None:
            raise ValueError("scheduled_mwh, metered_mwh, and lmp are required")

        n = len(_scheduled)
        if timestamps is None:
            base = _date or datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            timestamps = [base + _td(hours=i) for i in range(n)]

        assert len(_scheduled) == len(_metered) == len(_lmp) == len(timestamps), (
            f"Length mismatch: scheduled={len(_scheduled)}, metered={len(_metered)}, "
            f"lmp={len(_lmp)}, timestamps={len(timestamps)}"
        )
        intervals = [
            SettlementInterval(ts, s, m, p)
            for ts, s, m, p in zip(timestamps, _scheduled, _metered, _lmp)
        ]
        _final_date = _date or timestamps[0]
        stmt = SettlementStatement(asset_id, self.market, _final_date, intervals)
        logger.info(
            "Settlement for %s on %s: revenue=$%.2f, imbalance=$%.2f",
            asset_id, self.market, stmt.total_revenue, stmt.total_imbalance_charge,
        )
        return stmt
