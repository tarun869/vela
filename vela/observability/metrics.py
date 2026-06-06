"""Prometheus metrics collection for the Vela VPP backend."""
from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        Summary,
        REGISTRY,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not installed; metrics are no-ops")


def _make_counter(name: str, help: str, labels: list[str] | None = None):
    if not _PROMETHEUS_AVAILABLE:
        return None
    return Counter(name, help, labels or [])


def _make_gauge(name: str, help: str, labels: list[str] | None = None):
    if not _PROMETHEUS_AVAILABLE:
        return None
    return Gauge(name, help, labels or [])


def _make_histogram(name: str, help: str, labels: list[str] | None = None, buckets=None):
    if not _PROMETHEUS_AVAILABLE:
        return None
    kwargs = {"labelnames": labels or []}
    if buckets:
        kwargs["buckets"] = buckets
    return Histogram(name, help, **kwargs)


# --- Metrics definitions ---

dispatch_cycles_total = _make_counter(
    "vela_dispatch_cycles_total",
    "Total number of dispatch optimization cycles run",
    ["status", "market"],
)

dispatch_solve_duration_seconds = _make_histogram(
    "vela_dispatch_solve_duration_seconds",
    "Time taken to solve the MILP dispatch problem",
    ["market"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0],
)

asset_soc_gauge = _make_gauge(
    "vela_asset_soc",
    "Current state of charge for each asset (0-1)",
    ["asset_id"],
)

asset_power_mw = _make_gauge(
    "vela_asset_power_mw",
    "Current power output/consumption in MW (positive=discharge, negative=charge)",
    ["asset_id"],
)

settlement_revenue_usd = _make_counter(
    "vela_settlement_revenue_usd_total",
    "Total settlement revenue in USD",
    ["asset_id", "market"],
)

api_request_duration_seconds = _make_histogram(
    "vela_api_request_duration_seconds",
    "HTTP request duration by endpoint",
    ["method", "path", "status_code"],
)

market_bids_submitted = _make_counter(
    "vela_market_bids_submitted_total",
    "Total market bids submitted",
    ["market", "service"],
)

forecast_mae = _make_gauge(
    "vela_forecast_mae_usd_mwh",
    "Mean absolute error of LMP price forecasts",
    ["node", "model"],
)

worker_tasks_total = _make_counter(
    "vela_worker_tasks_total",
    "Total Celery tasks processed",
    ["task_name", "status"],
)


def track_duration(metric, **labels):
    """Decorator that records function duration in a Histogram metric."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if metric is None:
                return func(*args, **kwargs)
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = time.perf_counter() - start
                if labels:
                    metric.labels(**labels).observe(elapsed)
                else:
                    metric.observe(elapsed)
        return wrapper
    return decorator


def update_asset_metrics(asset_id: str, soc: float, power_mw: float) -> None:
    """Update per-asset gauge metrics."""
    if asset_soc_gauge:
        asset_soc_gauge.labels(asset_id=asset_id).set(soc)
    if asset_power_mw:
        asset_power_mw.labels(asset_id=asset_id).set(power_mw)


def get_metrics_text() -> tuple[bytes, str]:
    """Return Prometheus text-format metrics and content type."""
    if not _PROMETHEUS_AVAILABLE:
        return b"# prometheus_client not installed\n", "text/plain"
    return generate_latest(), CONTENT_TYPE_LATEST
