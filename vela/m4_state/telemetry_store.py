"""Time-series telemetry store with in-memory ring buffer."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Iterator


@dataclass
class TelemetryPoint:
    """A single telemetry measurement."""
    asset_id: str
    timestamp: float            # Unix timestamp
    metric: str                 # e.g., "power_mw", "soc", "temperature_c"
    value: float
    quality: int = 0            # 0=good, 1=suspect, 2=bad, 3=comm_lost
    unit: str = ""
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def is_good(self) -> bool:
        return self.quality == 0

    def age_seconds(self) -> float:
        return time.time() - self.timestamp


class AssetRingBuffer:
    """
    Per-asset ring buffer of TelemetryPoints for a single metric.

    Uses collections.deque for O(1) append and popleft.
    """

    def __init__(self, max_size: int = 1440) -> None:
        self._buffer: Deque[TelemetryPoint] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def append(self, point: TelemetryPoint) -> None:
        with self._lock:
            self._buffer.append(point)

    def latest(self) -> TelemetryPoint | None:
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    def last_n(self, n: int) -> list[TelemetryPoint]:
        with self._lock:
            buf = list(self._buffer)
        return buf[-n:] if len(buf) >= n else buf

    def range(self, start_ts: float, end_ts: float) -> list[TelemetryPoint]:
        """Return all points within [start_ts, end_ts]."""
        with self._lock:
            return [p for p in self._buffer if start_ts <= p.timestamp <= end_ts]

    def mean(self, last_n: int | None = None) -> float | None:
        """Compute mean value over last_n points (or all)."""
        with self._lock:
            pts = list(self._buffer) if last_n is None else list(self._buffer)[-last_n:]
        good = [p.value for p in pts if p.is_good]
        return sum(good) / len(good) if good else None

    def min_max(self) -> tuple[float, float] | None:
        with self._lock:
            vals = [p.value for p in self._buffer if p.is_good]
        if not vals:
            return None
        return min(vals), max(vals)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    def __iter__(self) -> Iterator[TelemetryPoint]:
        with self._lock:
            return iter(list(self._buffer))


class TelemetryStore:
    """
    In-memory ring buffer store for VPP asset telemetry.

    Organizes data as: asset_id → metric → AssetRingBuffer
    Supports bulk ingestion, per-asset queries, and aggregation.
    """

    def __init__(self, max_points_per_metric: int = 2880) -> None:
        """
        Args:
            max_points_per_metric: Ring buffer size per (asset, metric) pair.
                                   Default 2880 = 24h at 5-min intervals, or
                                   1 day at 30-sec intervals.
        """
        self._max_size = max_points_per_metric
        # {asset_id: {metric: AssetRingBuffer}}
        self._buffers: dict[str, dict[str, AssetRingBuffer]] = {}
        self._lock = threading.RLock()
        self._ingest_count = 0

    def _get_buffer(self, asset_id: str, metric: str) -> AssetRingBuffer:
        with self._lock:
            if asset_id not in self._buffers:
                self._buffers[asset_id] = {}
            if metric not in self._buffers[asset_id]:
                self._buffers[asset_id][metric] = AssetRingBuffer(self._max_size)
            return self._buffers[asset_id][metric]

    def ingest(self, point: TelemetryPoint) -> None:
        """Ingest a single telemetry point."""
        buf = self._get_buffer(point.asset_id, point.metric)
        buf.append(point)
        self._ingest_count += 1

    def ingest_batch(self, points: list[TelemetryPoint]) -> int:
        """Ingest a batch of telemetry points. Returns count ingested."""
        for p in points:
            self.ingest(p)
        return len(points)

    def ingest_dict(
        self,
        asset_id: str,
        timestamp: float,
        metrics: dict[str, float],
        quality: int = 0,
    ) -> None:
        """Convenience method to ingest a dict of metric→value pairs."""
        for metric, value in metrics.items():
            self.ingest(TelemetryPoint(
                asset_id=asset_id,
                timestamp=timestamp,
                metric=metric,
                value=value,
                quality=quality,
            ))

    def latest(self, asset_id: str, metric: str) -> TelemetryPoint | None:
        """Get the most recent telemetry point for an asset/metric pair."""
        buf = self._get_buffer(asset_id, metric)
        return buf.latest()

    def latest_value(self, asset_id: str, metric: str) -> float | None:
        """Get the latest value, or None if unavailable."""
        pt = self.latest(asset_id, metric)
        return pt.value if pt else None

    def history(
        self,
        asset_id: str,
        metric: str,
        last_n: int | None = None,
        start_ts: float | None = None,
        end_ts: float | None = None,
    ) -> list[TelemetryPoint]:
        """
        Query telemetry history.

        Either last_n points or a time range [start_ts, end_ts].
        """
        buf = self._get_buffer(asset_id, metric)
        if start_ts is not None and end_ts is not None:
            return buf.range(start_ts, end_ts)
        if last_n is not None:
            return buf.last_n(last_n)
        return list(buf)

    def asset_snapshot(self, asset_id: str) -> dict[str, float]:
        """Return a dict of all latest metric values for an asset."""
        with self._lock:
            metrics = self._buffers.get(asset_id, {})
        snapshot: dict[str, float] = {}
        for metric, buf in metrics.items():
            pt = buf.latest()
            if pt is not None:
                snapshot[metric] = pt.value
        return snapshot

    def all_asset_snapshots(self) -> dict[str, dict[str, float]]:
        """Return snapshots for all known assets."""
        with self._lock:
            asset_ids = list(self._buffers.keys())
        return {asset_id: self.asset_snapshot(asset_id) for asset_id in asset_ids}

    def aggregate_metric(
        self,
        metric: str,
        asset_ids: list[str] | None = None,
    ) -> float:
        """Sum the latest value of a metric across multiple assets."""
        with self._lock:
            ids = asset_ids or list(self._buffers.keys())
        total = 0.0
        for asset_id in ids:
            val = self.latest_value(asset_id, metric)
            if val is not None:
                total += val
        return total

    def stale_assets(
        self, metric: str = "power_mw", max_age_seconds: float = 300.0
    ) -> list[str]:
        """Return asset IDs whose latest telemetry is older than max_age_seconds."""
        with self._lock:
            ids = list(self._buffers.keys())
        stale = []
        for asset_id in ids:
            pt = self.latest(asset_id, metric)
            if pt is None or pt.age_seconds() > max_age_seconds:
                stale.append(asset_id)
        return stale

    def known_assets(self) -> list[str]:
        with self._lock:
            return list(self._buffers.keys())

    def known_metrics(self, asset_id: str) -> list[str]:
        with self._lock:
            return list(self._buffers.get(asset_id, {}).keys())

    @property
    def total_points_ingested(self) -> int:
        return self._ingest_count

    def clear_asset(self, asset_id: str) -> None:
        """Remove all telemetry for an asset."""
        with self._lock:
            self._buffers.pop(asset_id, None)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            total_buffers = sum(len(m) for m in self._buffers.values())
        return {
            "assets": len(self._buffers),
            "total_buffers": total_buffers,
            "total_ingested": self._ingest_count,
        }
