"""Debug tool for stepping through the MILP optimizer decision-making."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any


def print_dispatch_table(solution, lmp: list[float]) -> None:
    """Print a readable dispatch schedule table."""
    print("\n" + "=" * 80)
    print(f"Dispatch Schedule | Status: {solution.status} | Objective: ${solution.objective:.2f}")
    print("=" * 80)
    for asset_id in solution.charge_mw:
        print(f"\nAsset: {asset_id}")
        print(f"{'Hour':>5} {'LMP':>8} {'Charge':>8} {'Discharge':>10} {'SOC':>8} {'Rev':>10}")
        print("-" * 55)
        cumulative_rev = 0.0
        for t in range(len(lmp)):
            c = solution.charge_mw[asset_id][t]
            d = solution.discharge_mw[asset_id][t]
            soc = solution.soc[asset_id][t]
            rev = d * lmp[t]
            cumulative_rev += rev
            action = "CHARGE" if c > 0.01 else ("DISCH" if d > 0.01 else "IDLE ")
            print(f"{t:>5} {lmp[t]:>8.2f} {c:>8.3f} {d:>10.3f} {soc:>8.3f} {rev:>10.2f}  [{action}]")
        print(f"\n  Total revenue: ${cumulative_rev:.2f}")
    print("=" * 80)


def run_debug_session(
    capacity_mwh: float = 4.0,
    power_mw: float = 2.0,
    soc_init: float = 0.5,
    horizon: int = 24,
    lmp_scenario: str = "peak_valley",
) -> None:
    """Run the optimizer with a named LMP scenario and print the full dispatch table."""
    from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer
    import numpy as np

    scenarios: dict[str, list[float]] = {
        "flat": [50.0] * horizon,
        "peak_valley": [15.0] * 8 + [120.0] * 8 + [15.0] * max(0, horizon - 16),
        "morning_peak": [20.0] * 6 + [100.0] * 6 + [50.0] * max(0, horizon - 12),
        "spike": [30.0] * (horizon - 1) + [500.0],
        "negative": [-15.0] * 4 + [40.0] * (horizon - 8) + [-10.0] * 4,
        "caiso_typical": [
            25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
            50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38,
        ][:horizon],
    }

    lmp = scenarios.get(lmp_scenario, scenarios["flat"])
    if len(lmp) < horizon:
        lmp = (lmp * (horizon // len(lmp) + 1))[:horizon]

    print(f"\nRunning optimizer: scenario={lmp_scenario} horizon={horizon}h capacity={capacity_mwh}MWh power={power_mw}MW soc_init={soc_init}")

    asset = Asset(asset_id="debug-bat", capacity_mwh=capacity_mwh, power_mw=power_mw, soc_init=soc_init)
    optimizer = MILPDispatchOptimizer(horizon=horizon)
    solution = optimizer.solve(assets=[asset], lmp=lmp)

    print_dispatch_table(solution, lmp)
    print(f"\nSolve time: {solution.solve_time_s:.4f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vela Optimizer Debugger")
    parser.add_argument("--capacity", type=float, default=4.0, help="Battery capacity (MWh)")
    parser.add_argument("--power", type=float, default=2.0, help="Battery power rating (MW)")
    parser.add_argument("--soc", type=float, default=0.5, help="Initial SOC (0-1)")
    parser.add_argument("--horizon", type=int, default=24, help="Optimization horizon (hours)")
    parser.add_argument(
        "--scenario",
        default="caiso_typical",
        choices=["flat", "peak_valley", "morning_peak", "spike", "negative", "caiso_typical"],
        help="LMP price scenario",
    )
    args = parser.parse_args()
    run_debug_session(
        capacity_mwh=args.capacity,
        power_mw=args.power,
        soc_init=args.soc,
        horizon=args.horizon,
        lmp_scenario=args.scenario,
    )


if __name__ == "__main__":
    main()
