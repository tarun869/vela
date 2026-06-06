"""Simulation runner: Monte Carlo battery dispatch simulations."""
from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@dataclass
class SimConfig:
    n_scenarios: int = 100
    horizon_hours: int = 24
    capacity_mwh: float = 4.0
    power_mw: float = 2.0
    soc_init: float = 0.5
    rte: float = 0.92
    lmp_mean: float = 55.0
    lmp_std: float = 25.0
    lmp_daily_amplitude: float = 40.0
    seed: int = 42


@dataclass
class SimResult:
    scenario_id: int
    objective: float
    status: str
    total_discharge_mwh: float
    total_charge_mwh: float
    min_soc: float
    max_soc: float


@dataclass
class SimSummary:
    n_scenarios: int
    n_optimal: int
    mean_revenue: float
    std_revenue: float
    p10_revenue: float
    p50_revenue: float
    p90_revenue: float
    max_revenue: float
    min_revenue: float
    avg_solve_time_s: float
    config: SimConfig


def generate_lmp_scenario(config: SimConfig, scenario_id: int) -> list[float]:
    """Generate a single LMP price scenario with daily pattern + noise."""
    import numpy as np
    rng = np.random.default_rng(config.seed + scenario_id)
    daily_pattern = [
        config.lmp_mean + config.lmp_daily_amplitude * (-0.5 + 0.5 * abs(h - 19) / 12)
        for h in range(24)
    ]
    noise = rng.normal(0, config.lmp_std, config.horizon_hours)
    lmp = [max(0, daily_pattern[h % 24] + noise[h]) for h in range(config.horizon_hours)]
    return lmp


def run_simulation(config: SimConfig) -> SimSummary:
    """Run Monte Carlo dispatch simulations and return aggregate statistics."""
    from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer
    import numpy as np

    optimizer = MILPDispatchOptimizer(horizon=config.horizon_hours)
    results: list[SimResult] = []
    total_solve_time = 0.0

    for i in range(config.n_scenarios):
        lmp = generate_lmp_scenario(config, i)
        asset = Asset(
            asset_id="sim-bat",
            capacity_mwh=config.capacity_mwh,
            power_mw=config.power_mw,
            rte=config.rte,
            soc_init=config.soc_init,
        )
        t0 = time.perf_counter()
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        total_solve_time += time.perf_counter() - t0

        if solution.status in ("Optimal", "Feasible"):
            results.append(SimResult(
                scenario_id=i,
                objective=solution.objective,
                status=solution.status,
                total_discharge_mwh=sum(solution.discharge_mw["sim-bat"]),
                total_charge_mwh=sum(solution.charge_mw["sim-bat"]),
                min_soc=min(solution.soc["sim-bat"]),
                max_soc=max(solution.soc["sim-bat"]),
            ))

    revenues = np.array([r.objective for r in results])
    n_opt = len(results)

    return SimSummary(
        n_scenarios=config.n_scenarios,
        n_optimal=n_opt,
        mean_revenue=float(np.mean(revenues)) if n_opt > 0 else 0.0,
        std_revenue=float(np.std(revenues)) if n_opt > 0 else 0.0,
        p10_revenue=float(np.percentile(revenues, 10)) if n_opt > 0 else 0.0,
        p50_revenue=float(np.percentile(revenues, 50)) if n_opt > 0 else 0.0,
        p90_revenue=float(np.percentile(revenues, 90)) if n_opt > 0 else 0.0,
        max_revenue=float(np.max(revenues)) if n_opt > 0 else 0.0,
        min_revenue=float(np.min(revenues)) if n_opt > 0 else 0.0,
        avg_solve_time_s=total_solve_time / config.n_scenarios if config.n_scenarios > 0 else 0.0,
        config=config,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Vela Dispatch Simulation Runner")
    parser.add_argument("--scenarios", type=int, default=50)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--capacity", type=float, default=4.0)
    parser.add_argument("--power", type=float, default=2.0)
    parser.add_argument("--lmp-std", type=float, default=25.0)
    parser.add_argument("--output", default="sim_results.json")
    args = parser.parse_args()

    config = SimConfig(
        n_scenarios=args.scenarios,
        horizon_hours=args.horizon,
        capacity_mwh=args.capacity,
        power_mw=args.power,
        lmp_std=args.lmp_std,
    )

    logger.info("Starting simulation: %d scenarios, horizon=%dh", config.n_scenarios, config.horizon_hours)
    summary = run_simulation(config)

    logger.info("Simulation complete:")
    logger.info("  Optimal solutions: %d/%d", summary.n_optimal, summary.n_scenarios)
    logger.info("  Mean revenue: $%.2f", summary.mean_revenue)
    logger.info("  P10/P50/P90: $%.2f / $%.2f / $%.2f", summary.p10_revenue, summary.p50_revenue, summary.p90_revenue)
    logger.info("  Avg solve time: %.3fs", summary.avg_solve_time_s)

    output = {
        "n_scenarios": summary.n_scenarios,
        "n_optimal": summary.n_optimal,
        "mean_revenue_usd": round(summary.mean_revenue, 2),
        "std_revenue_usd": round(summary.std_revenue, 2),
        "p10_revenue_usd": round(summary.p10_revenue, 2),
        "p50_revenue_usd": round(summary.p50_revenue, 2),
        "p90_revenue_usd": round(summary.p90_revenue, 2),
        "avg_solve_time_s": round(summary.avg_solve_time_s, 4),
    }
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Results written to %s", args.output)


if __name__ == "__main__":
    main()
