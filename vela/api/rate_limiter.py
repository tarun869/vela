"""Token-bucket rate limiter (thread/async-safe)."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """
    Classic token-bucket algorithm.
    - capacity: maximum burst tokens
    - refill_rate: tokens added per second
    """
    capacity: float
    refill_rate: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self.refill_rate
        self._tokens = min(self.capacity, self._tokens + added)
        self._last_refill = now

    def consume_sync(self, tokens: float = 1.0) -> bool:
        """Attempt to consume tokens. Returns True if allowed, False if throttled."""
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    async def consume(self, tokens: float = 1.0) -> bool:
        """Async-safe token consumption."""
        async with self._lock:
            return self.consume_sync(tokens)

    @property
    def available_tokens(self) -> float:
        self._refill()
        return self._tokens


class RateLimiterRegistry:
    """Registry of per-key token buckets (e.g., per API key or IP)."""

    def __init__(
        self,
        capacity: float = 100.0,
        refill_rate: float = 10.0,
        max_buckets: int = 10_000,
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.max_buckets = max_buckets
        self._buckets: dict[str, TokenBucket] = {}

    def _get_bucket(self, key: str) -> TokenBucket:
        if key not in self._buckets:
            if len(self._buckets) >= self.max_buckets:
                # Simple eviction: remove oldest 10%
                evict_count = max(1, self.max_buckets // 10)
                for k in list(self._buckets.keys())[:evict_count]:
                    del self._buckets[k]
            self._buckets[key] = TokenBucket(
                capacity=self.capacity, refill_rate=self.refill_rate
            )
        return self._buckets[key]

    async def is_allowed(self, key: str, tokens: float = 1.0) -> bool:
        bucket = self._get_bucket(key)
        allowed = await bucket.consume(tokens)
        if not allowed:
            logger.warning("Rate limit hit for key=%s (available=%.2f)", key, bucket.available_tokens)
        return allowed

    def status(self, key: str) -> dict[str, float]:
        bucket = self._get_bucket(key)
        return {
            "available_tokens": bucket.available_tokens,
            "capacity": bucket.capacity,
            "refill_rate": bucket.refill_rate,
        }


# Default global registry
default_limiter = RateLimiterRegistry(capacity=200.0, refill_rate=20.0)
