"""Redis-backed cache implementation with JSON serialization."""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class RedisCache:
    """
    Thin wrapper around aioredis for async get/set/delete operations.
    Falls back gracefully if Redis is unavailable.
    """

    def __init__(self, url: str = _REDIS_URL, key_prefix: str = "vela") -> None:
        self.url = url
        self.key_prefix = key_prefix
        self._client = None

    async def _get_client(self):
        if self._client is None:
            try:
                import redis.asyncio as aioredis
                self._client = aioredis.from_url(self.url, decode_responses=True)
            except ImportError:
                logger.warning("redis package not installed; RedisCache will be a no-op")
        return self._client

    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}:{key}"

    async def get(self, key: str) -> Any | None:
        client = await self._get_client()
        if client is None:
            return None
        try:
            value = await client.get(self._make_key(key))
            if value is None:
                return None
            return json.loads(value)
        except Exception as exc:
            logger.warning("Redis GET failed key=%s: %s", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        try:
            serialized = json.dumps(value, default=str)
            await client.setex(self._make_key(key), ttl_seconds, serialized)
            return True
        except Exception as exc:
            logger.warning("Redis SET failed key=%s: %s", key, exc)
            return False

    async def delete(self, key: str) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        try:
            await client.delete(self._make_key(key))
            return True
        except Exception as exc:
            logger.warning("Redis DELETE failed key=%s: %s", key, exc)
            return False

    async def exists(self, key: str) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        try:
            return bool(await client.exists(self._make_key(key)))
        except Exception:
            return False

    async def keys(self, pattern: str = "*") -> list[str]:
        client = await self._get_client()
        if client is None:
            return []
        try:
            raw_keys = await client.keys(self._make_key(pattern))
            prefix = f"{self.key_prefix}:"
            return [k[len(prefix):] if k.startswith(prefix) else k for k in raw_keys]
        except Exception as exc:
            logger.warning("Redis KEYS failed pattern=%s: %s", pattern, exc)
            return []

    async def flush_prefix(self, prefix: str) -> int:
        """Delete all keys matching prefix:*"""
        keys = await self.keys(f"{prefix}:*")
        count = 0
        for k in keys:
            if await self.delete(k):
                count += 1
        return count

    async def ping(self) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        try:
            return await client.ping()
        except Exception:
            return False


# Singleton instance
cache = RedisCache()
