"""In-memory LRU cache with TTL support."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

V = TypeVar("V")


@dataclass
class _Entry:
    value: Any
    expires_at: float
    hits: int = 0


class LRUCache:
    """
    Thread-safe LRU cache with TTL eviction.
    Maximum size evicts least-recently-used items when at capacity.
    """

    def __init__(self, maxsize: int = 1024, default_ttl: int = 300) -> None:
        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self._store: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    def _is_live(self, entry: _Entry) -> bool:
        return time.monotonic() < entry.expires_at

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None or not self._is_live(entry):
                if entry is not None:
                    del self._store[key]
                self._misses += 1
                return None
            # Move to end (most recently used)
            self._store.move_to_end(key)
            entry.hits += 1
            self._hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else self.default_ttl
        async with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            elif len(self._store) >= self.maxsize:
                # Evict LRU (first item)
                evicted_key = next(iter(self._store))
                del self._store[evicted_key]
                logger.debug("LRU evict: %s", evicted_key)
            self._store[key] = _Entry(value=value, expires_at=time.monotonic() + ttl)

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "maxsize": self.maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
        }

    def get_sync(self, key: str) -> Any | None:
        """Synchronous get for non-async contexts."""
        entry = self._store.get(key)
        if entry is None or not self._is_live(entry):
            if entry is not None:
                del self._store[key]
            self._misses += 1
            return None
        self._store.move_to_end(key)
        entry.hits += 1
        self._hits += 1
        return entry.value

    def set_sync(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Synchronous set for non-async contexts."""
        ttl = ttl if ttl is not None else self.default_ttl
        if key in self._store:
            self._store.move_to_end(key)
        elif len(self._store) >= self.maxsize:
            del self._store[next(iter(self._store))]
        self._store[key] = _Entry(value=value, expires_at=time.monotonic() + ttl)


# Module-level default caches
forecast_cache = LRUCache(maxsize=256, default_ttl=300)
plan_cache = LRUCache(maxsize=512, default_ttl=3600)
telemetry_cache = LRUCache(maxsize=2048, default_ttl=30)
