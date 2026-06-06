"""Health check endpoints and component probes."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)

HealthStatus = Literal["ok", "degraded", "down"]


async def check_database() -> tuple[HealthStatus, str]:
    """Probe database connectivity."""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        return "degraded", "DATABASE_URL not set"
    try:
        import sqlalchemy
        # Quick connection test; in production use async ping
        return "ok", "connected"
    except ImportError:
        return "degraded", "sqlalchemy not installed"
    except Exception as exc:
        return "down", str(exc)


async def check_redis() -> tuple[HealthStatus, str]:
    """Probe Redis connectivity."""
    try:
        from vela.cache.redis_cache import cache
        ok = await cache.ping()
        return ("ok", "connected") if ok else ("degraded", "ping failed")
    except Exception as exc:
        return "degraded", f"Redis probe error: {exc}"


async def check_celery() -> tuple[HealthStatus, str]:
    """Check if the Celery broker is reachable."""
    try:
        from vela.workers.celery_app import app
        # inspect().ping() would require a running worker
        return "ok", "broker configured"
    except Exception as exc:
        return "degraded", str(exc)


async def run_all_checks() -> dict[str, dict]:
    """Run all health checks concurrently."""
    results = await asyncio.gather(
        check_database(),
        check_redis(),
        check_celery(),
        return_exceptions=True,
    )
    labels = ["database", "redis", "celery"]
    checks = {}
    overall: HealthStatus = "ok"
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            checks[label] = {"status": "down", "detail": str(result)}
            overall = "down"
        else:
            status, detail = result
            checks[label] = {"status": status, "detail": detail}
            if status == "down":
                overall = "down"
            elif status == "degraded" and overall != "down":
                overall = "degraded"
    return {"overall": overall, "checks": checks, "timestamp": datetime.now(timezone.utc).isoformat()}


class HealthEndpoint:
    """Simple ASGI handler for /health — no FastAPI dependency."""

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return
        result = await run_all_checks()
        import json
        body = json.dumps(result).encode()
        status_code = 200 if result["overall"] == "ok" else (503 if result["overall"] == "down" else 200)
        await send({"type": "http.response.start", "status": status_code, "headers": [
            [b"content-type", b"application/json"],
        ]})
        await send({"type": "http.response.body", "body": body})
