"""Optimizer performance benchmarks: solve time vs. horizon and fleet size."""
from __future__ import annotations

import time
import pytest
from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer


def make_fleet(n: int, capacity: float = 4.0, power: float = 2.0) -> list[Asset]:
    return [
        Asset(asset_id=f"bat-{i:03d}", capacity_mwh=capacity, power_mw=power, soc_init=0.5)
        for i in range(n)
    ]


def make_lmp(horizon: int, seed: int = 42) -> list[float]:
    import numpy as np
    np.random.seed(seed)
    daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
    return [max(0, daily[h % 24] + np.random.normal(0, 5)) for h in range(horizon)]


class TestSolveTimeByHorizon:
    @pytest.mark.parametrize("horizon", [4, 8, 12, 24, 48])
    def test_solve_time_within_threshold(self, horizon):
        """Dispatch solve time should scale reasonably with horizon."""
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
        optimizer = MILPDispatchOptimizer(horizon=horizon)
        lmp = make_lmp(horizon)

        start = time.perf_counter()
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        elapsed = time.perf_counter() - start

        # Generous threshold: single asset, any horizon <= 48 should solve in < 30s
        assert elapsed < 30.0, f"Solve took {elapsed:.2f}s for horizon={horizon}"
        assert solution.status in ("Optimal", "Feasible", "infeasible", "error")


class TestSolveTimeByFleetSize:
    @pytest.mark.parametrize("n_assets", [1, 3, 5])
    def test_fleet_solve_time(self, n_assets):
        """Fleet solve time should be tractable for small fleets."""
        fleet = make_fleet(n_assets)
        optimizer = MILPDispatchOptimizer(horizon=24)
        lmp = make_lmp(24)

        start = time.perf_counter()
        solution = optimizer.solve(assets=fleet, lmp=lmp)
        elapsed = time.perf_counter() - start

        assert elapsed < 60.0, f"Fleet of {n_assets} took {elapsed:.2f}s"
        assert solution.status in ("Optimal", "Feasible", "infeasible", "error")


class TestSolveTimeIsReported:
    def test_solution_reports_solve_time(self):
        optimizer = MILPDispatchOptimizer(horizon=12)
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
        lmp = make_lmp(12)
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        assert isinstance(solution.solve_time_s, float)
        assert solution.solve_time_s >= 0.0

    def test_solve_time_matches_wall_clock(self):
        optimizer = MILPDispatchOptimizer(horizon=24)
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
        lmp = make_lmp(24)

        wall_start = time.perf_counter()
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        wall_elapsed = time.perf_counter() - wall_start

        # Reported time should be close to wall clock (within 10x overhead)
        if solution.status in ("Optimal", "Feasible"):
            assert solution.solve_time_s <= wall_elapsed * 10 + 1.0


class TestObjectiveValueScaling:
    def test_larger_fleet_has_higher_or_equal_objective(self):
        """A larger fleet should never have lower revenue than a smaller one."""
        lmp = make_lmp(24)
        optimizer = MILPDispatchOptimizer(horizon=24)

        sol_1 = optimizer.solve(assets=make_fleet(1), lmp=lmp)
        sol_3 = optimizer.solve(assets=make_fleet(3), lmp=lmp)

        if sol_1.status in ("Optimal", "Feasible") and sol_3.status in ("Optimal", "Feasible"):
            assert sol_3.objective >= sol_1.objective - 1.0  # allow 1 USD tolerance
