"""Response caching decorator for FastAPI route handlers."""
from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)


def _make_key(prefix: str, *args: Any, **kwargs: Any) -> str:
    payload = json.dumps({"args": list(args), "kwargs": kwargs}, default=str, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{prefix}:{digest}"


def cached(ttl_seconds: int = 60, prefix: str = "route"):
    """
    Decorator that caches the return value of an async function for `ttl_seconds`.
    The cache is per-process in-memory (suitable for single-worker dev; use Redis in prod).
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _make_key(prefix or func.__name__, *args, **kwargs)
            now = time.monotonic()
            cached_entry = _CACHE.get(key)
            if cached_entry is not None:
                value, expires_at = cached_entry
                if now < expires_at:
                    logger.debug("Cache hit: %s", key)
                    return value

            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            _CACHE[key] = (result, now + ttl_seconds)
            logger.debug("Cache set: %s (ttl=%ds)", key, ttl_seconds)
            return result

        def invalidate(*args: Any, **kwargs: Any) -> None:
            key = _make_key(prefix or func.__name__, *args, **kwargs)
            _CACHE.pop(key, None)

        wrapper.invalidate = invalidate  # type: ignore[attr-defined]
        return wrapper

    return decorator


def invalidate_prefix(prefix: str) -> int:
    """Remove all cached entries whose key starts with the given prefix. Returns count removed."""
    keys_to_remove = [k for k in _CACHE if k.startswith(prefix)]
    for k in keys_to_remove:
        del _CACHE[k]
    return len(keys_to_remove)


def cache_stats() -> dict[str, Any]:
    now = time.monotonic()
    live = sum(1 for _, (_, exp) in _CACHE.items() if exp > now)
    return {"total_entries": len(_CACHE), "live_entries": live, "expired_entries": len(_CACHE) - live}
