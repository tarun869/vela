"""Efficient time-series store with pandas for analysis and resampling."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.warning("pandas/numpy not available; TimeSeriesStore will have limited functionality")


class TimeSeriesStore:
    """
    Pandas-backed time-series store for VPP analytics.

    Organizes data as: metric_name → pd.DataFrame with DatetimeIndex.
    Supports:
    - Ingestion from lists/dicts
    - Resampling and aggregation
    - Rolling statistics
    - Gap detection and interpolation
    - Export to parquet/CSV
    """

    def __init__(self) -> None:
        if not PANDAS_AVAILABLE:
            raise ImportError("pandas is required for TimeSeriesStore")
        self._series: dict[str, "pd.DataFrame"] = {}

    def ingest(
        self,
        metric: str,
        timestamps: list[datetime],
        values: list[float],
        asset_id: str = "",
        fill_gaps: bool = False,
        freq: str | None = None,
    ) -> None:
        """
        Ingest a list of (timestamp, value) pairs for a metric.

        Args:
            metric: Metric name (e.g., "power_mw", "lmp")
            timestamps: List of timezone-aware datetimes
            values: Corresponding float values
            asset_id: Optional asset ID column
            fill_gaps: If True, forward-fill missing intervals
            freq: Expected frequency (e.g., "5min", "1H") for gap detection
        """
        if not timestamps or not values:
            return
        idx = pd.DatetimeIndex(timestamps, tz="UTC" if timestamps[0].tzinfo else None)
        data: dict[str, Any] = {"value": values}
        if asset_id:
            data["asset_id"] = asset_id
        df = pd.DataFrame(data, index=idx).sort_index()
        df.index.name = "timestamp"

        if fill_gaps and freq is not None:
            full_idx = pd.date_range(idx.min(), idx.max(), freq=freq, tz=idx.tz)
            df = df.reindex(full_idx)
            df["value"] = df["value"].ffill()

        if metric in self._series:
            self._series[metric] = pd.concat(
                [self._series[metric], df]
            ).sort_index().loc[~pd.concat([self._series[metric], df]).index.duplicated(keep="last")]
        else:
            self._series[metric] = df
        logger.debug("Ingested %d points for metric '%s'", len(df), metric)

    def ingest_dataframe(self, metric: str, df: "pd.DataFrame") -> None:
        """Ingest a pre-built DataFrame directly."""
        if metric in self._series:
            combined = pd.concat([self._series[metric], df]).sort_index()
            self._series[metric] = combined[~combined.index.duplicated(keep="last")]
        else:
            self._series[metric] = df.sort_index()

    def get(
        self,
        metric: str,
        start: datetime | None = None,
        end: datetime | None = None,
        asset_id: str | None = None,
    ) -> "pd.DataFrame":
        """
        Retrieve time-series data for a metric.

        Returns an empty DataFrame if the metric is unknown.
        """
        df = self._series.get(metric, pd.DataFrame(columns=["value"]))
        if start is not None:
            df = df.loc[df.index >= pd.Timestamp(start)]
        if end is not None:
            df = df.loc[df.index <= pd.Timestamp(end)]
        if asset_id is not None and "asset_id" in df.columns:
            df = df[df["asset_id"] == asset_id]
        return df

    def latest_value(self, metric: str, asset_id: str | None = None) -> float | None:
        """Return the most recent value for a metric."""
        df = self.get(metric, asset_id=asset_id)
        if df.empty or "value" not in df.columns:
            return None
        return float(df["value"].iloc[-1])

    def resample(
        self,
        metric: str,
        freq: str,
        agg: str = "mean",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> "pd.DataFrame":
        """
        Resample a metric to a new frequency.

        Args:
            freq: Pandas offset alias (e.g., "1H", "15min", "1D")
            agg: Aggregation function ("mean", "sum", "max", "min", "last")
        """
        df = self.get(metric, start=start, end=end)
        if df.empty:
            return df
        numeric = df.select_dtypes(include="number")
        resampler = numeric.resample(freq)
        agg_func = getattr(resampler, agg, resampler.mean)
        return agg_func()

    def rolling_stats(
        self,
        metric: str,
        window: str,
        stats: list[str] | None = None,
    ) -> "pd.DataFrame":
        """
        Compute rolling statistics over a time window.

        Args:
            window: Pandas offset (e.g., "1H", "24H")
            stats: List of stats to compute ["mean", "std", "min", "max"]
        """
        df = self.get(metric)
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()
        stats = stats or ["mean", "std"]
        result = pd.DataFrame(index=df.index)
        roller = df["value"].rolling(window)
        for stat in stats:
            fn = getattr(roller, stat, None)
            if fn:
                result[f"rolling_{stat}"] = fn()
        return result

    def detect_gaps(
        self, metric: str, expected_freq: str = "5min", min_gap_multiples: int = 3
    ) -> list[tuple[datetime, datetime, timedelta]]:
        """
        Detect data gaps larger than min_gap_multiples * expected_freq.

        Returns list of (gap_start, gap_end, gap_duration) tuples.
        """
        df = self.get(metric)
        if df.empty or len(df) < 2:
            return []
        expected_delta = pd.tseries.frequencies.to_offset(expected_freq).nanos / 1e9  # seconds
        diffs = df.index.to_series().diff().dt.total_seconds().dropna()
        threshold = expected_delta * min_gap_multiples
        gap_mask = diffs > threshold
        gaps: list[tuple[datetime, datetime, timedelta]] = []
        for ts, dur in diffs[gap_mask].items():
            start_ts = ts - pd.Timedelta(seconds=dur)
            gaps.append((
                start_ts.to_pydatetime(),
                ts.to_pydatetime(),
                timedelta(seconds=dur),
            ))
        return gaps

    def interpolate_gaps(
        self, metric: str, method: str = "linear", limit: int = 12
    ) -> "pd.DataFrame":
        """
        Fill gaps in the time series via interpolation.

        Args:
            method: "linear", "time", "ffill", "bfill"
            limit: Maximum consecutive NaNs to fill
        """
        df = self.get(metric).copy()
        if df.empty or "value" not in df.columns:
            return df
        if method in ("ffill", "bfill"):
            df["value"] = df["value"].fillna(method=method, limit=limit)
        else:
            df["value"] = df["value"].interpolate(method=method, limit=limit)
        return df

    def daily_summary(
        self, metric: str, start: datetime | None = None, end: datetime | None = None
    ) -> "pd.DataFrame":
        """
        Compute daily summary statistics: sum, mean, min, max, count.
        """
        df = self.get(metric, start=start, end=end)
        if df.empty or "value" not in df.columns:
            return pd.DataFrame()
        return df["value"].resample("1D").agg(["sum", "mean", "min", "max", "count"])

    def energy_mwh(
        self,
        metric: str = "power_mw",
        start: datetime | None = None,
        end: datetime | None = None,
        interval_hours: float | None = None,
    ) -> float:
        """
        Integrate power (MW) over time to get energy (MWh).

        If interval_hours is not provided, infers from data frequency.
        """
        df = self.get(metric, start=start, end=end)
        if df.empty or "value" not in df.columns or len(df) < 2:
            return 0.0
        if interval_hours is None:
            median_seconds = df.index.to_series().diff().dt.total_seconds().median()
            interval_hours = median_seconds / 3600.0
        return float(df["value"].sum() * interval_hours)

    def lmp_weighted_revenue(
        self,
        power_metric: str = "power_mw",
        price_metric: str = "lmp",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> float:
        """
        Compute revenue = Σ power_mw[t] * lmp[t] * interval_hours[t].
        """
        power_df = self.get(power_metric, start=start, end=end)
        price_df = self.get(price_metric, start=start, end=end)
        if power_df.empty or price_df.empty:
            return 0.0
        # Align on common timestamps
        combined = power_df[["value"]].rename(columns={"value": "power"}).join(
            price_df[["value"]].rename(columns={"value": "price"}), how="inner"
        )
        if combined.empty:
            return 0.0
        # Estimate interval
        if len(combined) > 1:
            interval_hours = combined.index.to_series().diff().dt.total_seconds().median() / 3600.0
        else:
            interval_hours = 1.0
        return float((combined["power"] * combined["price"] * interval_hours).sum())

    def metrics(self) -> list[str]:
        """Return list of known metric names."""
        return list(self._series.keys())

    def size(self, metric: str) -> int:
        """Number of data points stored for a metric."""
        return len(self._series.get(metric, pd.DataFrame()))

    def drop(self, metric: str) -> None:
        """Remove a metric from the store."""
        self._series.pop(metric, None)

    def to_parquet(self, metric: str, path: str) -> None:
        """Export a metric's time series to a Parquet file."""
        df = self.get(metric)
        if not df.empty:
            df.to_parquet(path)
            logger.info("Exported metric '%s' to %s", metric, path)

    def from_parquet(self, metric: str, path: str) -> None:
        """Load a metric from a Parquet file."""
        df = pd.read_parquet(path)
        self.ingest_dataframe(metric, df)
        logger.info("Loaded metric '%s' from %s", metric, path)

    def to_dict(
        self, metric: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Export a metric to a list of dicts for JSON serialization."""
        df = self.get(metric, start=start, end=end)
        if df.empty:
            return []
        records = []
        for ts, row in df.iterrows():
            records.append({
                "timestamp": ts.isoformat(),
                **{k: v for k, v in row.items()},
            })
        return records
