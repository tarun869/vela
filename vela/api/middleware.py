"""Request logging and rate-limiting ASGI middleware."""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("vela.api.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured access log with request ID, method, path, status, and latency."""

    def __init__(self, app: ASGIApp, log_body: bool = False) -> None:
        super().__init__(app)
        self.log_body = log_body

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client": request.client.host if request.client else "unknown",
            },
        )
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 2))
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter keyed by client IP.
    Default: 200 requests / 60 seconds per IP.
    """

    def __init__(
        self,
        app: ASGIApp,
        requests_per_window: int = 200,
        window_seconds: int = 60,
        exclude_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.exclude_paths = set(exclude_paths or ["/health", "/metrics", "/docs", "/openapi.json"])
        # {ip: [(timestamp, count), ...]}
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        ip = self._get_client_ip(request)
        now = time.monotonic()
        window_start = now - self.window_seconds

        # Evict stale timestamps
        self._buckets[ip] = [ts for ts in self._buckets[ip] if ts > window_start]

        if len(self._buckets[ip]) >= self.requests_per_window:
            retry_after = int(self._buckets[ip][0] - window_start)
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )

        self._buckets[ip].append(now)
        remaining = self.requests_per_window - len(self._buckets[ip])
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_window)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(self.window_seconds)
        return response
