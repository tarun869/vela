"""
OSIsoft PI Historian integration for VPP time-series data archival.

Provides compressed time-series storage and retrieval using PI's
exception and compression deadband algorithms.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class PITag:
    tag_name: str
    description: str
    engineering_unit: str
    exception_deviation: float = 0.01   # % change to store new value
    compression_deviation: float = 0.02
    data_type: str = "float"


@dataclass
class PIValue:
    tag_name: str
    timestamp: float
    value: float
    quality: int = 0   # 0 = good


class PIHistorian:
    """
    Simulates OSIsoft PI Historian with exception and compression filtering.

    Exception: Store only when value changes by more than exception_deviation.
    Compression: Remove intermediate points that lie on a straight line.
    """

    def __init__(self) -> None:
        self._tags: Dict[str, PITag] = {}
        self._archive: Dict[str, List[PIValue]] = {}

    def add_tag(self, tag: PITag) -> None:
        self._tags[tag.tag_name] = tag
        self._archive[tag.tag_name] = []

    def write(self, tag_name: str, value: float, timestamp: Optional[float] = None) -> bool:
        """Write a value with exception filtering."""
        if tag_name not in self._tags:
            return False
        tag = self._tags[tag_name]
        ts = timestamp or time.time()
        archive = self._archive[tag_name]

        if archive:
            last_val = archive[-1].value
            pct_change = abs(value - last_val) / max(abs(last_val), 1e-9)
            if pct_change < tag.exception_deviation:
                return False   # Filtered by exception

        archive.append(PIValue(tag_name=tag_name, timestamp=ts, value=value))
        return True

    def read(
        self,
        tag_name: str,
        start: float,
        end: float,
        max_count: int = 10000,
    ) -> List[PIValue]:
        """Read raw archive data within time range."""
        archive = self._archive.get(tag_name, [])
        result = [v for v in archive if start <= v.timestamp <= end]
        return result[:max_count]

    def interpolated(
        self,
        tag_name: str,
        timestamps: List[float],
    ) -> List[Optional[float]]:
        """Linear interpolation at requested timestamps."""
        archive = self._archive.get(tag_name, [])
        if not archive:
            return [None] * len(timestamps)

        ts_arr = np.array([v.timestamp for v in archive])
        val_arr = np.array([v.value for v in archive])

        results: List[Optional[float]] = []
        for t in timestamps:
            idx = np.searchsorted(ts_arr, t)
            if idx == 0:
                results.append(float(val_arr[0]))
            elif idx >= len(ts_arr):
                results.append(float(val_arr[-1]))
            else:
                t0, t1 = ts_arr[idx - 1], ts_arr[idx]
                v0, v1 = val_arr[idx - 1], val_arr[idx]
                frac = (t - t0) / max(t1 - t0, 1e-9)
                results.append(float(v0 + frac * (v1 - v0)))
        return results

    def bulk_write(self, values: List[PIValue]) -> int:
        """Batch write with exception filtering. Returns accepted count."""
        return sum(1 for v in values if self.write(v.tag_name, v.value, v.timestamp))
