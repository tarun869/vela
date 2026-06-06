"""Load testing script: hammer the Vela API with concurrent requests."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@dataclass
class LoadTestResult:
    endpoint: str
    n_requests: int
    n_success: int
    n_error: int
    mean_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    rps: float


async def _single_request(session, method: str, url: str, json_body: dict | None = None) -> tuple[int, float]:
    """Make a single HTTP request and return (status_code, latency_ms)."""
    import aiohttp
    start = time.perf_counter()
    try:
        async with getattr(session, method.lower())(url, json=json_body) as resp:
            await resp.read()
            latency = (time.perf_counter() - start) * 1000
            return resp.status, latency
    except Exception as exc:
        latency = (time.perf_counter() - start) * 1000
        return 0, latency


async def load_test_endpoint(
    base_url: str,
    path: str,
    method: str = "GET",
    n_requests: int = 100,
    concurrency: int = 10,
    json_body: dict | None = None,
) -> LoadTestResult:
    """Run a load test against a single endpoint."""
    try:
        import aiohttp
    except ImportError:
        logger.error("aiohttp not installed: pip install aiohttp")
        return LoadTestResult(path, n_requests, 0, n_requests, 0, 0, 0, 0)

    url = f"{base_url}{path}"
    latencies: list[float] = []
    n_success = 0
    n_error = 0
    sem = asyncio.Semaphore(concurrency)

    async def bounded_request(session):
        nonlocal n_success, n_error
        async with sem:
            status, latency = await _single_request(session, method, url, json_body)
            latencies.append(latency)
            if 200 <= status < 300:
                n_success += 1
            else:
                n_error += 1

    wall_start = time.perf_counter()
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[bounded_request(session) for _ in range(n_requests)])
    wall_elapsed = time.perf_counter() - wall_start

    import numpy as np
    return LoadTestResult(
        endpoint=path,
        n_requests=n_requests,
        n_success=n_success,
        n_error=n_error,
        mean_latency_ms=round(float(np.mean(latencies)), 2),
        p95_latency_ms=round(float(np.percentile(latencies, 95)), 2),
        p99_latency_ms=round(float(np.percentile(latencies, 99)), 2),
        rps=round(n_requests / wall_elapsed, 2),
    )


async def run_suite(base_url: str, n: int = 100, concurrency: int = 10) -> None:
    endpoints = [
        ("GET", "/v1/assets/", None),
        ("GET", "/v1/market/prices?hours=6", None),
        ("POST", "/v1/forecasts/price", {"node": "TH_NP15_GEN-APND", "horizon_hours": 6}),
    ]

    print(f"\nLoad Test Suite: {base_url}")
    print(f"  Requests per endpoint: {n} | Concurrency: {concurrency}")
    print("=" * 70)
    print(f"{'Endpoint':<35} {'RPS':>8} {'Mean':>8} {'P95':>8} {'P99':>8} {'OK':>6}")
    print("-" * 70)

    for method, path, body in endpoints:
        result = await load_test_endpoint(base_url, path, method, n, concurrency, body)
        print(f"{path:<35} {result.rps:>8.1f} {result.mean_latency_ms:>8.1f} {result.p95_latency_ms:>8.1f} {result.p99_latency_ms:>8.1f} {result.n_success:>6}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vela Load Tester")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(run_suite(args.url, args.requests, args.concurrency))


if __name__ == "__main__":
    main()
