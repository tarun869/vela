"""Admin CLI commands."""
from __future__ import annotations

import json
import os


def cmd_health() -> None:
    """Check system health."""
    import asyncio
    from vela.observability.health import run_all_checks
    result = asyncio.run(run_all_checks())
    overall = result["overall"]
    status_icon = {"ok": "[OK]", "degraded": "[WARN]", "down": "[DOWN]"}[overall]
    print(f"System Health: {status_icon} {overall.upper()}")
    for name, check in result.get("checks", {}).items():
        icon = "[OK]" if check["status"] == "ok" else "[WARN]" if check["status"] == "degraded" else "[DOWN]"
        print(f"  {icon} {name}: {check['detail']}")


def cmd_cache_stats() -> None:
    """Print cache statistics."""
    from vela.api.cache import cache_stats
    stats = cache_stats()
    print("Cache Statistics:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


def cmd_slo_report() -> None:
    """Print SLO compliance report."""
    from vela.observability.slo import tracker
    print("SLO Report:")
    for slo in tracker.report():
        status = "FAIL" if slo["is_violating"] else "PASS"
        print(f"  [{status}] {slo['name']}: {slo['current']*100:.3f}% (target: {slo['target']*100:.1f}%)")
        print(f"    Budget remaining: {slo['error_budget_remaining']*100:.1f}%")
