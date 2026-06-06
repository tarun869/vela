"""Forecast-specific cache: keyed by node, horizon, and model type."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from vela.cache.memory_cache import LRUCache
from vela.cache.redis_cache import RedisCache

logger = logging.getLogger(__name__)

_LOCAL: LRUCache = LRUCache(maxsize=512, default_ttl=300)
_REDIS: RedisCache = RedisCache(key_prefix="vela:forecast")


def _forecast_key(node: str, horizon_hours: int, model: str, ts_floor_minutes: int = 5) -> str:
    """Build a deterministic cache key bucketed by time floor."""
    now = datetime.utcnow()
    floored_minute = (now.minute // ts_floor_minutes) * ts_floor_minutes
    ts_str = now.strftime(f"%Y%m%d%H{floored_minute:02d}")
    raw = f"{node}:{horizon_hours}:{model}:{ts_str}"
    return hashlib.md5(raw.encode()).hexdigest()


async def get_forecast(
    node: str,
    horizon_hours: int,
    model: str = "ar",
) -> dict[str, Any] | None:
    """
    Try L1 (in-memory) then L2 (Redis) for a cached forecast.
    Returns None on cache miss.
    """
    key = _forecast_key(node, horizon_hours, model)

    # L1 check
    result = _LOCAL.get_sync(key)
    if result is not None:
        logger.debug("Forecast L1 hit: node=%s horizon=%d", node, horizon_hours)
        return result

    # L2 check
    result = await _REDIS.get(key)
    if result is not None:
        logger.debug("Forecast L2 hit: node=%s horizon=%d", node, horizon_hours)
        _LOCAL.set_sync(key, result, ttl=60)  # promote to L1 with shorter TTL
        return result

    logger.debug("Forecast cache miss: node=%s horizon=%d", node, horizon_hours)
    return None


async def set_forecast(
    node: str,
    horizon_hours: int,
    model: str,
    forecast: dict[str, Any],
    ttl_seconds: int = 300,
) -> None:
    """Store a forecast in both L1 and L2 caches."""
    key = _forecast_key(node, horizon_hours, model)
    _LOCAL.set_sync(key, forecast, ttl=min(ttl_seconds, 300))
    await _REDIS.set(key, forecast, ttl_seconds=ttl_seconds)
    logger.debug("Forecast cached: node=%s horizon=%d ttl=%ds", node, horizon_hours, ttl_seconds)


async def invalidate_node(node: str) -> int:
    """Invalidate all cached forecasts for a node."""
    await _REDIS.flush_prefix(f"*{node}*")
    await _LOCAL.clear()  # conservative: clear all local
    return 1
