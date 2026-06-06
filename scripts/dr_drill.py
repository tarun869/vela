"""Demand response drill simulator: test VPP response to a DR event."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@dataclass
class DREvent:
    event_id: str
    event_type: str  # "emergency", "economic", "test"
    requested_mw: float
    start_time: datetime
    duration_minutes: int = 60
    price_usd_mwh: float = 250.0


@dataclass
class DRDrillResult:
    event: DREvent
    assets_dispatched: list[str]
    target_mw: float
    achieved_mw: float
    response_time_s: float
    compliance_pct: float
    estimated_revenue_usd: float
    passed: bool


async def simulate_dr_event(
    event: DREvent,
    asset_ids: list[str] | None = None,
    capacity_per_asset_mw: float = 2.0,
) -> DRDrillResult:
    """
    Simulate a demand response event by dispatching available assets.
    Returns a DRDrillResult with compliance metrics.
    """
    import numpy as np
    np.random.seed(42)
    t0 = time.perf_counter()

    asset_ids = asset_ids or ["bat-001", "bat-002", "bat-003"]
    logger.info(
        "DR DRILL: event=%s type=%s requested=%.1f MW duration=%dm",
        event.event_id, event.event_type, event.requested_mw, event.duration_minutes,
    )

    # Simulate asset response with realistic dispatch delays
    await asyncio.sleep(0.1)  # Simulate telemetry round-trip

    dispatched_assets = []
    achieved_mw = 0.0

    for asset_id in asset_ids:
        if achieved_mw >= event.requested_mw:
            break
        # Simulate 90-99% delivery rate per asset
        delivery_rate = np.random.uniform(0.88, 0.99)
        asset_mw = min(capacity_per_asset_mw, event.requested_mw - achieved_mw) * delivery_rate
        achieved_mw += asset_mw
        dispatched_assets.append(asset_id)
        logger.info("  Dispatched %s: %.3f MW", asset_id, asset_mw)

    response_time_s = time.perf_counter() - t0
    compliance = achieved_mw / event.requested_mw if event.requested_mw > 0 else 1.0
    duration_h = event.duration_minutes / 60
    revenue = achieved_mw * event.price_usd_mwh * duration_h
    passed = compliance >= 0.95

    result = DRDrillResult(
        event=event,
        assets_dispatched=dispatched_assets,
        target_mw=event.requested_mw,
        achieved_mw=round(achieved_mw, 3),
        response_time_s=round(response_time_s, 3),
        compliance_pct=round(compliance * 100, 2),
        estimated_revenue_usd=round(revenue, 2),
        passed=passed,
    )

    status = "PASS" if passed else "FAIL"
    logger.info(
        "DR DRILL RESULT: [%s] Achieved=%.1f/%.1f MW | Compliance=%.1f%% | Revenue=$%.2f | ResponseTime=%.3fs",
        status, achieved_mw, event.requested_mw, result.compliance_pct, revenue, response_time_s,
    )
    return result


async def run_drill_suite() -> None:
    """Run a sequence of DR drill scenarios."""
    now = datetime.now(timezone.utc)
    drills = [
        DREvent("drill-test-001", "test", requested_mw=3.0, start_time=now, duration_minutes=30),
        DREvent("drill-eco-001", "economic", requested_mw=5.0, start_time=now, price_usd_mwh=150.0),
        DREvent("drill-emerg-001", "emergency", requested_mw=8.0, start_time=now, price_usd_mwh=500.0),
    ]

    results = []
    for event in drills:
        result = await simulate_dr_event(event)
        results.append(result)
        await asyncio.sleep(0.05)

    print("\nDR Drill Summary:")
    print(f"{'Event ID':<20} {'Type':<12} {'Target':>8} {'Achieved':>10} {'Compliance':>12} {'Revenue':>12} {'Pass?':>6}")
    print("-" * 85)
    for r in results:
        print(f"{r.event.event_id:<20} {r.event.event_type:<12} {r.target_mw:>8.1f} {r.achieved_mw:>10.1f} {r.compliance_pct:>11.1f}% ${r.estimated_revenue_usd:>11.2f} {'YES' if r.passed else 'NO':>6}")
    all_pass = all(r.passed for r in results)
    print(f"\nOverall: {'ALL PASS' if all_pass else 'SOME FAILED'}")


if __name__ == "__main__":
    asyncio.run(run_drill_suite())
