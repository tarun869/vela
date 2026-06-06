"""Meter Data Management (MDM) for interval meter data processing."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class IntervalRecord(NamedTuple):
    meter_id: str
    asset_id: str
    interval_start: datetime
    interval_end: datetime
    energy_mwh: float
    reactive_mvarh: float = 0.0
    quality: str = "good"
    estimated: bool = False


@dataclass
class MDMProcessor:
    """
    Meter Data Management processor for VPP assets.

    Handles:
    - Interval data ingestion (15-min, 30-min, 60-min)
    - Data quality validation
    - Gap filling and estimation
    - Aggregation to settlement intervals
    - Export to settlement systems (CAISO, ERCOT)
    """
    interval_minutes: int = 15
    max_gap_intervals: int = 4   # Maximum consecutive missing intervals to fill
    suspect_threshold_mwh: float = 999.9  # Readings above this are suspect

    def validate_readings(
        self,
        readings: list[IntervalRecord],
    ) -> tuple[list[IntervalRecord], list[str]]:
        """
        Validate and flag meter readings.

        Returns (validated_readings, issue_log).
        """
        validated = []
        issues = []

        for r in readings:
            energy = r.energy_mwh
            quality = r.quality
            flagged = False

            if energy > self.suspect_threshold_mwh:
                issues.append(f"Suspect high reading: {r.meter_id} at {r.interval_start}: {energy} MWh")
                quality = "suspect"
                flagged = True

            if energy < -self.suspect_threshold_mwh:
                issues.append(f"Suspect low reading: {r.meter_id} at {r.interval_start}: {energy} MWh")
                quality = "suspect"
                flagged = True

            if not flagged:
                validated.append(r)
            else:
                validated.append(IntervalRecord(
                    meter_id=r.meter_id,
                    asset_id=r.asset_id,
                    interval_start=r.interval_start,
                    interval_end=r.interval_end,
                    energy_mwh=energy,
                    reactive_mvarh=r.reactive_mvarh,
                    quality=quality,
                    estimated=r.estimated,
                ))

        return validated, issues

    def fill_gaps(
        self,
        readings: list[IntervalRecord],
        expected_start: datetime,
        expected_end: datetime,
    ) -> list[IntervalRecord]:
        """
        Detect and fill gaps in the interval time series.

        Uses linear interpolation for short gaps, 0 for long gaps.
        """
        dt = timedelta(minutes=self.interval_minutes)
        # Build lookup
        reading_map: dict[datetime, IntervalRecord] = {r.interval_start: r for r in readings}

        filled = []
        current = expected_start
        prev_value: float | None = None

        while current < expected_end:
            if current in reading_map:
                r = reading_map[current]
                filled.append(r)
                prev_value = r.energy_mwh
            else:
                # Find next available reading
                next_val = 0.0
                for ahead in range(1, self.max_gap_intervals + 2):
                    next_ts = current + dt * ahead
                    if next_ts in reading_map:
                        next_val = reading_map[next_ts].energy_mwh
                        break

                # Interpolate
                if prev_value is not None:
                    est_value = (prev_value + next_val) / 2.0
                else:
                    est_value = next_val

                est = IntervalRecord(
                    meter_id=(readings[0].meter_id if readings else ""),
                    asset_id=(readings[0].asset_id if readings else ""),
                    interval_start=current,
                    interval_end=current + dt,
                    energy_mwh=est_value,
                    quality="estimated",
                    estimated=True,
                )
                filled.append(est)
                logger.debug("Estimated interval at %s: %.4f MWh", current, est_value)

            current += dt

        return filled

    def aggregate_to_hourly(
        self,
        sub_hourly_readings: list[IntervalRecord],
    ) -> list[IntervalRecord]:
        """
        Aggregate sub-hourly (15-min or 30-min) readings to hourly totals.

        Used for settlement in hourly markets.
        """
        from collections import defaultdict
        hourly_buckets: dict[datetime, list[IntervalRecord]] = defaultdict(list)

        for r in sub_hourly_readings:
            hour_start = r.interval_start.replace(minute=0, second=0, microsecond=0)
            hourly_buckets[hour_start].append(r)

        hourly = []
        for hour_start in sorted(hourly_buckets.keys()):
            records = hourly_buckets[hour_start]
            total_energy = sum(r.energy_mwh for r in records)
            total_reactive = sum(r.reactive_mvarh for r in records)
            has_estimated = any(r.estimated for r in records)
            has_suspect = any(r.quality == "suspect" for r in records)

            quality = "suspect" if has_suspect else ("estimated" if has_estimated else "good")
            hourly.append(IntervalRecord(
                meter_id=records[0].meter_id,
                asset_id=records[0].asset_id,
                interval_start=hour_start,
                interval_end=hour_start + timedelta(hours=1),
                energy_mwh=total_energy,
                reactive_mvarh=total_reactive,
                quality=quality,
                estimated=has_estimated,
            ))

        return hourly

    def compute_daily_profile(
        self,
        readings: list[IntervalRecord],
    ) -> dict[str, float]:
        """Compute daily summary statistics from interval data."""
        if not readings:
            return {}
        energies = np.array([r.energy_mwh for r in readings])
        gen_intervals = energies[energies > 0]
        load_intervals = energies[energies < 0]

        return {
            "total_generation_mwh": float(np.sum(gen_intervals)),
            "total_consumption_mwh": float(abs(np.sum(load_intervals))),
            "net_export_mwh": float(np.sum(energies)),
            "peak_power_mw": float(np.max(energies) * (60 / self.interval_minutes)),
            "min_power_mw": float(np.min(energies) * (60 / self.interval_minutes)),
            "n_intervals": float(len(readings)),
            "estimated_fraction": float(np.mean([r.estimated for r in readings])),
        }
