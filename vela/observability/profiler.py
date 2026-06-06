"""Performance profiling utilities for the Vela backend."""
from __future__ import annotations

import cProfile
import io
import logging
import pstats
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


@contextmanager
def profile_block(name: str = "block", top_n: int = 20):
    """Context manager that profiles a code block and logs the top N functions."""
    profiler = cProfile.Profile()
    profiler.enable()
    start = time.perf_counter()
    try:
        yield profiler
    finally:
        profiler.disable()
        elapsed_ms = (time.perf_counter() - start) * 1000
        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats("cumulative")
        stats.print_stats(top_n)
        logger.info("[profiler] %s: %.2f ms\n%s", name, elapsed_ms, stream.getvalue())


def profile(func: Callable) -> Callable:
    """Decorator that profiles a function and logs timing."""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with profile_block(func.__qualname__):
            return func(*args, **kwargs)
    return wrapper


class Stopwatch:
    """Simple wall-clock stopwatch for manual timing."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._laps: list[tuple[str, float]] = []
        self._start: float = time.perf_counter()

    def lap(self, label: str = "") -> float:
        now = time.perf_counter()
        elapsed = now - self._start
        self._laps.append((label, elapsed))
        return elapsed

    def report(self) -> dict[str, Any]:
        total = time.perf_counter() - self._start
        return {
            "name": self.name,
            "total_ms": round(total * 1000, 3),
            "laps": [(label, round(t * 1000, 3)) for label, t in self._laps],
        }

    def log(self) -> None:
        r = self.report()
        logger.info("[stopwatch] %s: %.2f ms | laps=%s", r["name"], r["total_ms"], r["laps"])


class FunctionTimer:
    """Accumulates timing stats across multiple calls to a function."""

    def __init__(self) -> None:
        self._calls: dict[str, list[float]] = {}

    def record(self, name: str, duration_s: float) -> None:
        self._calls.setdefault(name, []).append(duration_s)

    def summary(self) -> dict[str, dict[str, float]]:
        import statistics
        result = {}
        for name, timings in self._calls.items():
            result[name] = {
                "calls": len(timings),
                "mean_ms": round(statistics.mean(timings) * 1000, 3),
                "p50_ms": round(statistics.median(timings) * 1000, 3),
                "p95_ms": round(sorted(timings)[int(len(timings) * 0.95)] * 1000, 3) if len(timings) >= 20 else None,
                "max_ms": round(max(timings) * 1000, 3),
            }
        return result


global_timer = FunctionTimer()
