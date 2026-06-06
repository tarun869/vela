"""Historical load profile builder and analysis utilities."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from collections import defaultdict
from typing import NamedTuple


class LoadProfileStats(NamedTuple):
    mean_by_hour: np.ndarray       # shape (24,)
    std_by_hour: np.ndarray        # shape (24,)
    mean_by_dow: np.ndarray        # shape (7,)
    peak_hour: int
    off_peak_hour: int
    load_factor: float             # avg / peak
    annual_energy_mwh: float


@dataclass
class LoadProfileBuilder:
    """
    Builds representative load profiles from historical interval meter data.

    Profiles are used for:
    - Day-ahead dispatch scheduling
    - Baseline calculations (DRAM, DR programs)
    - Capacity planning
    - Seasonal adjustment
    """
    interval_minutes: int = 60  # 15, 30, or 60 minute intervals
    _records: list[tuple[datetime, float]] = field(default_factory=list, init=False, repr=False)

    def add_interval(self, timestamp: datetime, load_mw: float) -> None:
        """Add a single interval observation."""
        if load_mw < 0:
            raise ValueError(f"Negative load not allowed: {load_mw}")
        self._records.append((timestamp, load_mw))

    def add_bulk(self, timestamps: list[datetime], loads: list[float]) -> None:
        """Add multiple intervals at once."""
        for ts, load in zip(timestamps, loads):
            self.add_interval(ts, load)

    def _group_by_hour(self) -> dict[int, list[float]]:
        by_hour: dict[int, list[float]] = defaultdict(list)
        for ts, load in self._records:
            by_hour[ts.hour].append(load)
        return by_hour

    def _group_by_dow(self) -> dict[int, list[float]]:
        by_dow: dict[int, list[float]] = defaultdict(list)
        for ts, load in self._records:
            by_dow[ts.weekday()].append(load)
        return by_dow

    def compute_stats(self) -> LoadProfileStats:
        """Compute summary statistics across all historical data."""
        if not self._records:
            raise RuntimeError("No records loaded")

        loads = np.array([r[1] for r in self._records])
        by_hour = self._group_by_hour()
        by_dow = self._group_by_dow()

        mean_by_hour = np.array([np.mean(by_hour.get(h, [0.0])) for h in range(24)])
        std_by_hour = np.array([np.std(by_hour.get(h, [0.0])) for h in range(24)])
        mean_by_dow = np.array([np.mean(by_dow.get(d, [0.0])) for d in range(7)])

        peak_hour = int(np.argmax(mean_by_hour))
        off_peak_hour = int(np.argmin(mean_by_hour))
        peak_load = np.max(loads)
        avg_load = np.mean(loads)
        load_factor = float(avg_load / peak_load) if peak_load > 0 else 0.0
        dt_hours = self.interval_minutes / 60.0
        annual_energy = float(avg_load * len(loads) * dt_hours)

        return LoadProfileStats(
            mean_by_hour=mean_by_hour,
            std_by_hour=std_by_hour,
            mean_by_dow=mean_by_dow,
            peak_hour=peak_hour,
            off_peak_hour=off_peak_hour,
            load_factor=load_factor,
            annual_energy_mwh=annual_energy,
        )

    def typical_day_profile(
        self,
        target_date: date,
        similar_days: int = 10,
    ) -> np.ndarray:
        """
        Build a 24-hour typical load profile for a target date.

        Selects `similar_days` historical days with matching day-of-week
        and season, then returns the mean profile.

        Returns
        -------
        np.ndarray
            Shape (24,) in MW
        """
        target_dow = target_date.weekday()
        target_month = target_date.month
        # Group records by date
        by_date: dict[date, list[tuple[int, float]]] = defaultdict(list)
        for ts, load in self._records:
            by_date[ts.date()].append((ts.hour, load))

        candidate_hours: list[np.ndarray] = []
        for d, intervals in by_date.items():
            if d.weekday() != target_dow:
                continue
            if abs(d.month - target_month) > 1 and not (
                (d.month == 12 and target_month == 1) or
                (d.month == 1 and target_month == 12)
            ):
                continue
            if d == target_date:
                continue
            hourly = np.zeros(24)
            counts = np.zeros(24)
            for h, load in intervals:
                hourly[h] += load
                counts[h] += 1
            valid = counts > 0
            if valid.sum() >= 20:  # at least 20 hours of data
                hourly[valid] /= counts[valid]
                candidate_hours.append(hourly)

        if not candidate_hours:
            # Fall back to overall mean by hour
            stats = self.compute_stats()
            return stats.mean_by_hour

        # Use most recent `similar_days` candidates
        recent = candidate_hours[-similar_days:]
        return np.mean(np.array(recent), axis=0)

    def seasonal_adjustment_factors(self) -> dict[int, float]:
        """
        Compute monthly scaling factors relative to annual average.

        Returns dict mapping month (1-12) -> scaling factor.
        """
        by_month: dict[int, list[float]] = defaultdict(list)
        for ts, load in self._records:
            by_month[ts.month].append(load)

        annual_mean = np.mean([r[1] for r in self._records])
        factors = {}
        for m in range(1, 13):
            if m in by_month:
                factors[m] = float(np.mean(by_month[m]) / (annual_mean + 1e-6))
            else:
                factors[m] = 1.0
        return factors

    def peak_demand_analysis(self, top_n: int = 100) -> dict[str, float]:
        """
        Identify and characterize peak demand events.

        Returns statistics on the top-N peak intervals.
        """
        if not self._records:
            raise RuntimeError("No records loaded")
        loads = np.array([r[1] for r in self._records])
        threshold_idx = np.argsort(loads)[-top_n:]
        peak_loads = loads[threshold_idx]
        peak_hours = np.array([self._records[i][0].hour for i in threshold_idx])

        return {
            "peak_mw": float(np.max(peak_loads)),
            "avg_top_n_mw": float(np.mean(peak_loads)),
            "p95_mw": float(np.percentile(loads, 95)),
            "p99_mw": float(np.percentile(loads, 99)),
            "most_common_peak_hour": int(np.bincount(peak_hours).argmax()),
            "peak_load_factor": float(np.mean(loads) / np.max(loads)),
        }

    def generate_synthetic_year(
        self,
        base_mw: float = 100.0,
        seed: int = 0,
    ) -> tuple[list[datetime], list[float]]:
        """
        Generate synthetic annual load data for testing.

        Returns (timestamps, loads).
        """
        rng = np.random.default_rng(seed)
        start = datetime(2025, 1, 1, 0, 0)
        n = 8760
        timestamps = [start + timedelta(hours=i) for i in range(n)]
        loads = []
        for dt in timestamps:
            hour_f = 1 + 0.3 * np.sin(2 * np.pi * (dt.hour - 6) / 24)
            dow_f = 0.85 if dt.weekday() >= 5 else 1.0
            doy = dt.timetuple().tm_yday
            season_f = 1 + 0.15 * np.sin(2 * np.pi * (doy - 80) / 365)
            noise = 1 + 0.03 * rng.standard_normal()
            loads.append(float(max(10.0, base_mw * hour_f * dow_f * season_f * noise)))
        return timestamps, loads
