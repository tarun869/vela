"""Secret management: AWS Secrets Manager with local .env fallback."""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


class SecretManager:
    """
    Retrieves secrets from AWS Secrets Manager with a local environment fallback.
    Caches results to avoid repeated API calls during a process lifetime.
    """

    def __init__(self, region: str = "us-west-2") -> None:
        self.region = region
        self._cache: dict[str, Any] = {}

    def get_secret(self, secret_name: str, key: str | None = None) -> str | dict:
        """
        Fetch a secret by name.
        If `key` is provided, return only that field from a JSON secret.
        Falls back to os.environ if AWS is not configured.
        """
        if secret_name in self._cache:
            cached = self._cache[secret_name]
        else:
            cached = self._fetch(secret_name)
            self._cache[secret_name] = cached

        if key and isinstance(cached, dict):
            return cached.get(key, "")
        return cached

    def _fetch(self, secret_name: str) -> str | dict:
        """Try AWS Secrets Manager first, then fall back to environment."""
        try:
            import boto3
            from botocore.exceptions import ClientError

            client = boto3.client("secretsmanager", region_name=self.region)
            response = client.get_secret_value(SecretId=secret_name)
            raw = response.get("SecretString", response.get("SecretBinary", ""))
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return raw

        except ImportError:
            logger.debug("boto3 not installed; falling back to env for secret '%s'", secret_name)
        except Exception as exc:
            logger.warning("AWS Secrets Manager failed for '%s': %s — using env fallback", secret_name, exc)

        # Fallback: look for an env var matching the secret name (uppercased, dashes to underscores)
        env_key = secret_name.upper().replace("-", "_").replace("/", "_")
        env_val = os.getenv(env_key, "")
        if not env_val:
            logger.warning("Secret '%s' not found in AWS or environment", secret_name)
        return env_val

    def invalidate(self, secret_name: str | None = None) -> None:
        """Clear cached secret(s)."""
        if secret_name:
            self._cache.pop(secret_name, None)
        else:
            self._cache.clear()


@lru_cache(maxsize=1)
def get_secret_manager() -> SecretManager:
    return SecretManager(region=os.getenv("AWS_REGION", "us-west-2"))


def get_secret(name: str, key: str | None = None) -> str | dict:
    """Module-level convenience function."""
    return get_secret_manager().get_secret(name, key)


# Commonly used secrets with typed accessors

def get_db_url() -> str:
    return str(os.getenv("DATABASE_URL") or get_secret("vela/database", "url"))


def get_jwt_secret() -> str:
    return str(os.getenv("JWT_SECRET") or get_secret("vela/jwt", "secret") or "insecure-dev-secret")


def get_redis_url() -> str:
    return str(os.getenv("REDIS_URL") or get_secret("vela/redis", "url") or "redis://localhost:6379/0")
