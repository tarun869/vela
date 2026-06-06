"""Replay historical market data through the dispatch optimizer."""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def generate_synthetic_history(days: int = 30, seed: int = 42) -> list[dict]:
    """Generate synthetic hourly LMP history for replay."""
    import numpy as np
    np.random.seed(seed)
    daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    history = []
    for d in range(days):
        for h in range(24):
            ts = now - timedelta(days=days - d) + timedelta(hours=h)
            lmp = max(0.0, daily[h] + np.random.normal(0, 8))
            history.append({
                "timestamp": ts.isoformat(),
                "node": "TH_NP15_GEN-APND",
                "lmp": round(lmp, 2),
                "market": "CAISO",
            })
    return history


def replay(
    history: list[dict],
    capacity_mwh: float = 4.0,
    power_mw: float = 2.0,
    window_hours: int = 24,
    step_hours: int = 1,
    verbose: bool = False,
) -> list[dict]:
    """
    Rolling-window replay: for each step, optimize dispatch using the next window_hours of LMP data.
    Returns a list of per-interval dispatch + settlement results.
    """
    from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer
    from vela.m9_settlement.settlement_engine import SettlementEngine
    import numpy as np

    optimizer = MILPDispatchOptimizer(horizon=window_hours)
    engine = SettlementEngine(market="CAISO")
    asset = Asset(asset_id="replay-bat", capacity_mwh=capacity_mwh, power_mw=power_mw, soc_init=0.5)

    results = []
    total_revenue = 0.0
    prices = [r["lmp"] for r in history]

    for i in range(0, len(prices) - window_hours, step_hours):
        window = prices[i : i + window_hours]
        solution = optimizer.solve(assets=[asset], lmp=window)
        if solution.status not in ("Optimal", "Feasible"):
            continue

        # Update SOC for next window
        asset = Asset(
            asset_id="replay-bat",
            capacity_mwh=capacity_mwh,
            power_mw=power_mw,
            soc_init=solution.soc["replay-bat"][-1],
        )

        # Settle the first interval only
        discharge = solution.discharge_mw["replay-bat"][0]
        lmp_now = window[0]
        rev = discharge * lmp_now
        total_revenue += rev

        entry = {
            "timestamp": history[i]["timestamp"],
            "lmp": round(lmp_now, 2),
            "discharge_mw": round(discharge, 3),
            "charge_mw": round(solution.charge_mw["replay-bat"][0], 3),
            "soc": round(solution.soc["replay-bat"][0], 4),
            "interval_revenue_usd": round(rev, 4),
            "cumulative_revenue_usd": round(total_revenue, 4),
        }
        results.append(entry)
        if verbose:
            logger.info(
                "[%s] LMP=$%.2f | Discharge=%.3fMW | SOC=%.3f | Rev=$%.2f | Cum=$%.2f",
                entry["timestamp"][:16], lmp_now, discharge, entry["soc"], rev, total_revenue,
            )

    logger.info("Replay complete: %d intervals | Total revenue: $%.2f", len(results), total_revenue)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Vela Market Replay Tool")
    parser.add_argument("--days", type=int, default=7, help="Days of history to replay")
    parser.add_argument("--capacity", type=float, default=4.0)
    parser.add_argument("--power", type=float, default=2.0)
    parser.add_argument("--window", type=int, default=24, help="Optimization window (hours)")
    parser.add_argument("--output", default="replay_results.json")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    history = generate_synthetic_history(days=args.days)
    results = replay(
        history=history,
        capacity_mwh=args.capacity,
        power_mw=args.power,
        window_hours=args.window,
        verbose=args.verbose,
    )

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("Results written to %s", args.output)


if __name__ == "__main__":
    main()
