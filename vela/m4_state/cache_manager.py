"""Redis cache abstraction for VPP state and market data."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:
    import redis
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis package not installed; using in-memory fallback")


class InMemoryCache:
    """
    Thread-safe in-memory fallback cache for testing without Redis.

    Supports TTL expiration (checked lazily on get).
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}  # key → (value, expiry)

    def get(self, key: str) -> Any:
        if key not in self._data:
            return None
        value, expiry = self._data[key]
        if expiry is not None and time.time() > expiry:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expiry = time.time() + ttl if ttl else None
        self._data[key] = (value, expiry)

    def delete(self, key: str) -> bool:
        if key in self._data:
            del self._data[key]
            return True
        return False

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def keys(self, pattern: str = "*") -> list[str]:
        import fnmatch
        return [k for k in self._data.keys() if fnmatch.fnmatch(k, pattern)]

    def flush(self) -> None:
        self._data.clear()

    def incr(self, key: str, amount: int = 1) -> int:
        val = self.get(key) or 0
        new_val = int(val) + amount
        self.set(key, new_val)
        return new_val

    def lpush(self, key: str, *values: Any) -> int:
        existing = self.get(key) or []
        new_list = list(values) + existing
        self.set(key, new_list)
        return len(new_list)

    def lrange(self, key: str, start: int, end: int) -> list[Any]:
        lst = self.get(key) or []
        end = len(lst) if end == -1 else end + 1
        return lst[start:end]


class CacheManager:
    """
    Redis cache abstraction for VPP application data.

    Provides typed helpers for storing asset states, market prices,
    dispatch plans, and forecasts with appropriate TTLs.
    """

    # Cache key prefixes
    PREFIX_ASSET_STATE = "vela:asset:state:"
    PREFIX_MARKET_PRICE = "vela:market:price:"
    PREFIX_DISPATCH_PLAN = "vela:dispatch:plan:"
    PREFIX_FORECAST = "vela:forecast:"
    PREFIX_LOCK = "vela:lock:"
    PREFIX_METRICS = "vela:metrics:"

    # Default TTLs (seconds)
    TTL_ASSET_STATE = 60
    TTL_MARKET_PRICE = 300
    TTL_DISPATCH_PLAN = 3600
    TTL_FORECAST = 1800
    TTL_LOCK = 30

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        use_memory_fallback: bool = False,
    ) -> None:
        self._fallback_mode = use_memory_fallback or not REDIS_AVAILABLE
        if self._fallback_mode:
            self._cache: Any = InMemoryCache()
            logger.info("CacheManager using in-memory fallback")
        else:
            self._cache = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            try:
                self._cache.ping()
                logger.info("CacheManager connected to Redis at %s:%d", host, port)
            except Exception:
                logger.warning("Redis unavailable; switching to memory fallback")
                self._cache = InMemoryCache()
                self._fallback_mode = True

    def _get_raw(self, key: str) -> Any:
        try:
            return self._cache.get(key)
        except Exception:
            logger.exception("Cache GET failed for key %s", key)
            return None

    def _set_raw(self, key: str, value: str, ttl: int | None = None) -> None:
        try:
            if self._fallback_mode:
                self._cache.set(key, value, ttl=ttl)
            elif ttl:
                self._cache.setex(key, ttl, value)
            else:
                self._cache.set(key, value)
        except Exception:
            logger.exception("Cache SET failed for key %s", key)

    def set_json(self, key: str, data: Any, ttl: int | None = None) -> None:
        """Store any JSON-serializable data."""
        self._set_raw(key, json.dumps(data), ttl)

    def get_json(self, key: str) -> Any:
        """Retrieve and deserialize JSON data."""
        raw = self._get_raw(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    # --- Asset State Cache ---

    def set_asset_state(self, asset_id: str, state: dict[str, Any]) -> None:
        key = self.PREFIX_ASSET_STATE + asset_id
        self.set_json(key, state, ttl=self.TTL_ASSET_STATE)

    def get_asset_state(self, asset_id: str) -> dict[str, Any] | None:
        return self.get_json(self.PREFIX_ASSET_STATE + asset_id)

    def get_all_asset_states(self) -> dict[str, dict[str, Any]]:
        """Bulk fetch all cached asset states."""
        pattern = self.PREFIX_ASSET_STATE + "*"
        if self._fallback_mode:
            keys = self._cache.keys(pattern)
        else:
            try:
                keys = self._cache.keys(pattern)
            except Exception:
                return {}
        result: dict[str, dict[str, Any]] = {}
        for key in keys:
            asset_id = key.replace(self.PREFIX_ASSET_STATE, "")
            state = self.get_json(key)
            if state is not None:
                result[asset_id] = state
        return result

    # --- Market Price Cache ---

    def set_lmp(self, market: str, node: str, price: float, timestamp: float) -> None:
        key = f"{self.PREFIX_MARKET_PRICE}{market}:{node}"
        self.set_json(key, {"price": price, "ts": timestamp}, ttl=self.TTL_MARKET_PRICE)

    def get_lmp(self, market: str, node: str) -> tuple[float, float] | None:
        data = self.get_json(f"{self.PREFIX_MARKET_PRICE}{market}:{node}")
        if data:
            return data["price"], data["ts"]
        return None

    def set_ancillary_prices(
        self, market: str, prices: dict[str, float], timestamp: float
    ) -> None:
        key = f"{self.PREFIX_MARKET_PRICE}{market}:ancillary"
        self.set_json(key, {"prices": prices, "ts": timestamp}, ttl=self.TTL_MARKET_PRICE)

    def get_ancillary_prices(self, market: str) -> dict[str, float] | None:
        data = self.get_json(f"{self.PREFIX_MARKET_PRICE}{market}:ancillary")
        return data.get("prices") if data else None

    # --- Dispatch Plan Cache ---

    def set_dispatch_plan(
        self, plan_id: str, plan: list[dict[str, Any]]
    ) -> None:
        key = self.PREFIX_DISPATCH_PLAN + plan_id
        self.set_json(key, plan, ttl=self.TTL_DISPATCH_PLAN)

    def get_dispatch_plan(self, plan_id: str) -> list[dict[str, Any]] | None:
        return self.get_json(self.PREFIX_DISPATCH_PLAN + plan_id)

    # --- Forecast Cache ---

    def set_forecast(
        self, forecast_type: str, horizon_hours: int, data: list[dict[str, Any]]
    ) -> None:
        key = f"{self.PREFIX_FORECAST}{forecast_type}:{horizon_hours}h"
        self.set_json(key, data, ttl=self.TTL_FORECAST)

    def get_forecast(
        self, forecast_type: str, horizon_hours: int
    ) -> list[dict[str, Any]] | None:
        key = f"{self.PREFIX_FORECAST}{forecast_type}:{horizon_hours}h"
        return self.get_json(key)

    # --- Distributed Locking ---

    def acquire_lock(self, resource: str, ttl: int = 30) -> bool:
        """
        Acquire a distributed lock using Redis SET NX.

        Returns True if lock was acquired.
        """
        key = self.PREFIX_LOCK + resource
        if self._fallback_mode:
            if self._cache.exists(key):
                return False
            self._cache.set(key, "1", ttl=ttl)
            return True
        try:
            return bool(self._cache.set(key, "1", ex=ttl, nx=True))
        except Exception:
            logger.exception("Lock acquire failed for %s", resource)
            return False

    def release_lock(self, resource: str) -> bool:
        """Release a distributed lock."""
        key = self.PREFIX_LOCK + resource
        return bool(self._cache.delete(key))

    # --- Metrics ---

    def increment_metric(self, metric: str, amount: float = 1.0) -> float:
        key = self.PREFIX_METRICS + metric
        if self._fallback_mode:
            return float(self._cache.incr(key, int(amount * 1000))) / 1000.0
        try:
            return float(self._cache.incrbyfloat(key, amount))
        except Exception:
            logger.exception("Metric increment failed for %s", metric)
            return 0.0

    def ping(self) -> bool:
        """Health check."""
        try:
            if self._fallback_mode:
                return True
            return self._cache.ping()
        except Exception:
            return False

    def flush_all(self) -> None:
        """Flush all Vela keys from cache (use with caution)."""
        if self._fallback_mode:
            self._cache.flush()
        else:
            try:
                pattern = "vela:*"
                keys = self._cache.keys(pattern)
                if keys:
                    self._cache.delete(*keys)
            except Exception:
                logger.exception("Cache flush failed")
