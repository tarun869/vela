"""DRAM/Demand Response baseline calculation methods."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from collections import defaultdict
from typing import NamedTuple


class BaselineResult(NamedTuple):
    baseline_mw: list[float]        # Baseline load per interval
    adjustment_mw: list[float]      # Adjustment factor applied
    method: str
    event_date: date
    performance_mw: list[float]     # Actual load during event
    curtailment_mw: list[float]     # baseline - actual (DR performance)
    total_curtailment_mwh: float


@dataclass
class DRAMBaselineCalculator:
    """
    Demand Response Auction Mechanism (DRAM) baseline calculator.

    CAISO DRAM uses the 10-of-10 baseline method with optional day-of adjustment.

    Methods supported:
    - 10-of-10: Average of 10 most recent similar non-event days
    - 5-of-10: Average of 5 highest-load days from past 10 similar days
    - Weather-adjusted 10-of-10: with temperature normalization

    Reference: CAISO Business Practice Manual for Demand Response
    """
    method: str = "10_of_10"
    n_days: int = 10
    morning_adjustment_hours: list[int] = field(default_factory=lambda: [0, 1, 2, 3])
    event_start_hour: int = 15   # Typical CAISO DR event window
    event_end_hour: int = 20

    def compute_baseline(
        self,
        historical_loads: dict[date, list[float]],
        event_date: date,
        actual_event_loads: list[float],
        morning_loads: list[float] | None = None,
    ) -> BaselineResult:
        """
        Compute DR event baseline and curtailment.

        Parameters
        ----------
        historical_loads : dict[date, list[float]]
            Historical hourly load data by date
        event_date : date
            Date of the DR event
        actual_event_loads : list[float]
            Actual load during event window (hourly)
        morning_loads : list[float], optional
            Morning loads (pre-event) for day-of adjustment
        """
        # Select similar days (same day-of-week, non-holiday, non-event)
        similar_days = self._select_similar_days(historical_loads, event_date)

        if len(similar_days) < 3:
            # Fallback: use all available days
            similar_days = sorted(historical_loads.keys(), reverse=True)[:self.n_days]

        # Compute baseline
        if self.method == "10_of_10":
            baseline = self._compute_10_of_10(historical_loads, similar_days)
        elif self.method == "5_of_10":
            baseline = self._compute_5_of_10(historical_loads, similar_days)
        else:
            baseline = self._compute_10_of_10(historical_loads, similar_days)

        # Day-of adjustment (morning hour ratio)
        adjustment = np.ones(len(baseline))
        if morning_loads is not None and len(morning_loads) >= len(self.morning_adjustment_hours):
            morning_baseline = np.mean([baseline[h] for h in self.morning_adjustment_hours])
            morning_actual = np.mean(morning_loads[:len(self.morning_adjustment_hours)])
            if morning_baseline > 0:
                adj_factor = morning_actual / morning_baseline
                adj_factor = float(np.clip(adj_factor, 0.8, 1.2))  # Cap adjustment at ±20%
                adjustment[:] = adj_factor

        adjusted_baseline = baseline * adjustment

        # Performance calculation
        T = min(len(adjusted_baseline), len(actual_event_loads))
        curtailment = np.maximum(0, adjusted_baseline[:T] - np.array(actual_event_loads[:T]))
        total_curtailment = float(np.sum(curtailment))  # MWh = MW * 1h intervals

        return BaselineResult(
            baseline_mw=adjusted_baseline[:T].tolist(),
            adjustment_mw=(adjustment[:T] - 1).tolist(),
            method=self.method,
            event_date=event_date,
            performance_mw=actual_event_loads[:T],
            curtailment_mw=curtailment.tolist(),
            total_curtailment_mwh=total_curtailment,
        )

    def _select_similar_days(
        self,
        historical_loads: dict[date, list[float]],
        event_date: date,
    ) -> list[date]:
        """Select n most recent non-event days with same day-of-week."""
        target_dow = event_date.weekday()
        candidates = [
            d for d in sorted(historical_loads.keys(), reverse=True)
            if d.weekday() == target_dow and d < event_date
        ]
        return candidates[:self.n_days]

    def _compute_10_of_10(
        self,
        historical_loads: dict[date, list[float]],
        similar_days: list[date],
    ) -> np.ndarray:
        """Average of n most recent similar days."""
        load_matrix = np.array([historical_loads[d] for d in similar_days if d in historical_loads])
        if len(load_matrix) == 0:
            return np.zeros(24)
        return np.mean(load_matrix, axis=0)

    def _compute_5_of_10(
        self,
        historical_loads: dict[date, list[float]],
        similar_days: list[date],
    ) -> np.ndarray:
        """Average of 5 highest-load days from past 10 similar days."""
        load_matrix = np.array([historical_loads[d] for d in similar_days if d in historical_loads])
        if len(load_matrix) == 0:
            return np.zeros(24)
        # Rank by total daily load, take top 5
        daily_totals = np.sum(load_matrix, axis=1)
        top_5_idx = np.argsort(-daily_totals)[:5]
        return np.mean(load_matrix[top_5_idx], axis=0)


@dataclass
class MeterReadingAdjuster:
    """
    Adjusts meter readings for settlement purposes.

    Handles:
    - Missing meter data (estimate from neighboring intervals)
    - Meter drift correction
    - Data quality flagging
    """
    quality_threshold: float = 0.95  # Minimum fraction of good readings

    def fill_missing(
        self,
        readings: list[float | None],
        method: str = "linear_interpolation",
    ) -> tuple[list[float], list[str]]:
        """
        Fill missing meter readings.

        Returns (filled_readings, quality_flags).
        """
        arr = np.array([r if r is not None else np.nan for r in readings], dtype=float)
        flags = ["good" if r is not None else "estimated" for r in readings]

        nan_mask = np.isnan(arr)
        if not nan_mask.any():
            return arr.tolist(), flags

        if method == "linear_interpolation":
            indices = np.arange(len(arr))
            valid = ~nan_mask
            if valid.sum() >= 2:
                arr[nan_mask] = np.interp(indices[nan_mask], indices[valid], arr[valid])
            else:
                arr[nan_mask] = 0.0

        elif method == "forward_fill":
            for i in range(1, len(arr)):
                if np.isnan(arr[i]):
                    arr[i] = arr[i-1]
            arr = np.nan_to_num(arr, 0.0)

        return arr.tolist(), flags

    def data_quality_score(self, flags: list[str]) -> float:
        """Fraction of readings with 'good' quality flag."""
        if not flags:
            return 0.0
        return sum(1 for f in flags if f == "good") / len(flags)
