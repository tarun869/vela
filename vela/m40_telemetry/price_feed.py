"""Historical ERCOT RT LMP replay for demo / backtesting price streams."""
from __future__ import annotations

import asyncio
import csv
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from .models import PriceTick

logger = logging.getLogger(__name__)

# Seconds in one ERCOT RT settlement interval (15 min). Divided by the speed
# multiplier to set demo replay pace.
INTERVAL_SECONDS = 900.0

# Bundled fixture CSVs live at <repo>/tests/fixtures/ercot_lmp/.
_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ercot_lmp"


class ERCOTHistoricalReplay:
    """Replays a day of historical ERCOT RT LMP data as a :class:`PriceTick` stream."""

    def __init__(
        self,
        date: str,
        node: str = "HB_HUBZONE",
        speed_multiplier: float = 30.0,
        window_start_hour: int = 16,
        window_end_hour: int = 20,
        replay_from_hour: int = 0,
        loop: bool = False,
        fixture_dir: Path | None = None,
    ) -> None:
        self.date = date
        self.node = node
        self.speed_multiplier = speed_multiplier
        self.window_start_hour = window_start_hour
        self.window_end_hour = window_end_hour
        # Demo aids: skip the quiet overnight hours and loop the day so the
        # interesting price action is on screen within seconds, repeatedly.
        self.replay_from_hour = replay_from_hour
        self.loop = loop
        self._fixture_dir = fixture_dir or _FIXTURE_DIR

    @property
    def csv_path(self) -> Path:
        filename = f"ercot_{self.date.replace('-', '_')}_{self.node}.csv"
        return self._fixture_dir / filename

    def load_ticks(self) -> list[PriceTick]:
        """Load CSV rows (from ``replay_from_hour`` onward) into PriceTicks."""
        path = self.csv_path
        if not path.exists():
            raise FileNotFoundError(f"ERCOT replay fixture not found: {path}")
        ticks: list[PriceTick] = []
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                ts = row["interval_start"]
                hour = int(ts[11:13]) if len(ts) >= 13 else 0
                if hour < self.replay_from_hour:
                    continue
                ticks.append(
                    PriceTick(
                        timestamp=ts,
                        node=row["settlement_point"],
                        lmp_per_mwh=float(row["lmp"]),
                        energy_component=float(row["energy"]),
                        congestion_component=float(row["congestion"]),
                        loss_component=float(row["loss"]),
                        interval_type="historical_replay",
                    )
                )
        return ticks

    async def stream(self) -> AsyncGenerator[PriceTick, None]:
        """Yield one PriceTick per CSV row, paced by ``speed_multiplier``.

        With ``loop=True`` the (trimmed) day repeats forever so the demo keeps
        cycling through the afternoon price spike.
        """
        delay = INTERVAL_SECONDS / self.speed_multiplier if self.speed_multiplier > 0 else 0.0
        ticks = self.load_ticks()
        while True:
            for tick in ticks:
                yield tick
                if delay > 0:
                    await asyncio.sleep(delay)
            if not self.loop:
                break
