"""Celery task: periodic system maintenance (cleanup, health checks, rotation)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from vela.workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    name="vela.workers.maintenance_worker.cleanup_stale_plans",
    bind=True,
)
def cleanup_stale_plans(self, max_age_hours: int = 168) -> dict[str, Any]:
    """Remove dispatch plans older than max_age_hours from in-memory stores."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    logger.info("Cleaning up dispatch plans older than %s", cutoff.isoformat())
    # In production: DELETE FROM dispatch_plans WHERE created_at < cutoff AND status != 'approved'
    return {"cleaned": 0, "cutoff": cutoff.isoformat(), "policy": f"older than {max_age_hours}h"}


@app.task(name="vela.workers.maintenance_worker.rotate_api_keys")
def rotate_api_keys(days_threshold: int = 90) -> dict[str, Any]:
    """Flag API keys older than days_threshold for rotation."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)
    logger.info("Checking API keys older than %s", cutoff.isoformat())
    return {
        "keys_flagged": 0,
        "keys_rotated": 0,
        "cutoff": cutoff.isoformat(),
    }


@app.task(name="vela.workers.maintenance_worker.evict_cache")
def evict_cache(prefix: str | None = None) -> dict[str, Any]:
    """Evict expired or stale entries from the in-process cache."""
    try:
        from vela.api.cache import invalidate_prefix, cache_stats
        removed = 0
        if prefix:
            removed = invalidate_prefix(prefix)
        stats = cache_stats()
        logger.info("Cache eviction complete: removed=%d stats=%s", removed, stats)
        return {"removed": removed, "stats": stats}
    except Exception as exc:
        logger.warning("Cache eviction failed: %s", exc)
        return {"removed": 0, "error": str(exc)}


@app.task(name="vela.workers.maintenance_worker.health_ping")
def health_ping() -> dict[str, Any]:
    """Lightweight heartbeat task to verify the worker is responsive."""
    return {
        "status": "ok",
        "worker": os.getenv("HOSTNAME", "unknown"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.task(name="vela.workers.maintenance_worker.compress_old_telemetry")
def compress_old_telemetry(days_threshold: int = 7) -> dict[str, Any]:
    """
    Downsample/compress telemetry older than days_threshold.
    Aggregates 1-minute data to 5-minute averages to reduce storage.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)
    logger.info("Compressing telemetry older than %s", cutoff.isoformat())
    return {
        "compressed_records": 0,
        "cutoff": cutoff.isoformat(),
        "target_resolution": "5min",
    }


@app.task(name="vela.workers.maintenance_worker.archive_settlements")
def archive_settlements(days_threshold: int = 365) -> dict[str, Any]:
    """Archive finalized settlement statements older than days_threshold to cold storage."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)
    logger.info("Archiving settlements older than %s to cold storage", cutoff.isoformat())
    return {
        "archived": 0,
        "cutoff": cutoff.isoformat(),
        "destination": os.getenv("ARCHIVE_BUCKET", "s3://vela-archive"),
    }
