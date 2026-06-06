"""Optimizer result cache: stores dispatch plans keyed by inputs hash."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from vela.cache.memory_cache import LRUCache
from vela.cache.redis_cache import RedisCache

logger = logging.getLogger(__name__)

_LOCAL: LRUCache = LRUCache(maxsize=128, default_ttl=600)
_REDIS: RedisCache = RedisCache(key_prefix="vela:optimizer")


def _plan_cache_key(
    asset_ids: list[str],
    lmp: list[float],
    horizon_hours: int,
    market: str,
) -> str:
    """
    Deterministic cache key for a dispatch optimization run.
    Rounded LMP values to avoid float noise causing spurious cache misses.
    """
    rounded_lmp = [round(v, 1) for v in lmp]
    payload = json.dumps({
        "assets": sorted(asset_ids),
        "lmp": rounded_lmp,
        "horizon": horizon_hours,
        "market": market,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


async def get_plan(
    asset_ids: list[str],
    lmp: list[float],
    horizon_hours: int,
    market: str = "CAISO",
) -> dict[str, Any] | None:
    """Look up a previously computed dispatch plan."""
    key = _plan_cache_key(asset_ids, lmp, horizon_hours, market)

    result = _LOCAL.get_sync(key)
    if result is not None:
        logger.debug("Optimizer L1 hit key=%s", key[:8])
        return result

    result = await _REDIS.get(key)
    if result is not None:
        logger.debug("Optimizer L2 hit key=%s", key[:8])
        _LOCAL.set_sync(key, result, ttl=120)
        return result

    return None


async def set_plan(
    asset_ids: list[str],
    lmp: list[float],
    horizon_hours: int,
    plan: dict[str, Any],
    market: str = "CAISO",
    ttl_seconds: int = 600,
) -> None:
    """Store a dispatch plan in both cache layers."""
    key = _plan_cache_key(asset_ids, lmp, horizon_hours, market)
    _LOCAL.set_sync(key, plan, ttl=min(ttl_seconds, 600))
    await _REDIS.set(key, plan, ttl_seconds=ttl_seconds)
    logger.debug("Optimizer plan cached key=%s ttl=%ds", key[:8], ttl_seconds)


async def invalidate_all() -> None:
    """Clear all optimizer caches. Called when assets change or prices are stale."""
    await _LOCAL.clear()
    await _REDIS.flush_prefix("*")
    logger.info("Optimizer cache invalidated")
