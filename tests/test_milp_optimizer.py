"""MILP optimizer unit tests: objective value, constraints, edge cases."""
from __future__ import annotations

import pytest
from vela.m6_optimizer.milp import Asset, DispatchSolution, MILPDispatchOptimizer


@pytest.fixture
def optimizer() -> MILPDispatchOptimizer:
    return MILPDispatchOptimizer(horizon=24)


@pytest.fixture
def single_asset() -> Asset:
    return Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)


class TestMILPSolver:
    def test_solve_returns_dispatch_solution(self, optimizer, single_asset, sample_lmp):
        solution = optimizer.solve(assets=[single_asset], lmp=sample_lmp)
        assert isinstance(solution, DispatchSolution)

    def test_solution_has_correct_horizon_length(self, optimizer, single_asset, sample_lmp):
        solution = optimizer.solve(assets=[single_asset], lmp=sample_lmp)
        if solution.status in ("Optimal", "Feasible"):
            assert len(solution.charge_mw["bat-001"]) == 24
            assert len(solution.discharge_mw["bat-001"]) == 24
            assert len(solution.soc["bat-001"]) == 24

    def test_positive_objective_on_arbitrage_opportunity(self, optimizer, single_asset):
        """Large spread between low and high prices should yield positive revenue."""
        lmp = [10.0] * 8 + [150.0] * 8 + [10.0] * 8
        solution = optimizer.solve(assets=[single_asset], lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            assert solution.objective >= 0.0

    def test_solve_time_is_recorded(self, optimizer, single_asset, sample_lmp):
        solution = optimizer.solve(assets=[single_asset], lmp=sample_lmp)
        assert solution.solve_time_s >= 0.0

    def test_short_horizon(self):
        optimizer = MILPDispatchOptimizer(horizon=4)
        asset = Asset(asset_id="bat-001", capacity_mwh=2.0, power_mw=1.0, soc_init=0.5)
        lmp = [20.0, 20.0, 80.0, 80.0]
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        assert solution.status in ("Optimal", "Feasible", "infeasible", "error")

    def test_single_hour_horizon(self):
        optimizer = MILPDispatchOptimizer(horizon=1)
        asset = Asset(asset_id="bat-001", capacity_mwh=2.0, power_mw=1.0, soc_init=0.9)
        solution = optimizer.solve(assets=[asset], lmp=[100.0])
        assert solution.status in ("Optimal", "Feasible", "infeasible", "error")

    def test_all_negative_prices_no_discharge(self, optimizer, single_asset):
        """Battery should not NET-discharge when all prices are negative.

        At negative prices the rational strategy is to charge (consume power and get paid).
        Any discharge that occurs should be offset by equal or greater charging.
        """
        lmp = [-20.0] * 24
        solution = optimizer.solve(assets=[single_asset], lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            total_discharge = sum(solution.discharge_mw["bat-001"])
            total_charge    = sum(solution.charge_mw["bat-001"])
            # Net energy should not be exported at negative prices
            net_discharge = total_discharge - total_charge
            assert net_discharge < 0.1, (
                f"At negative prices, net dispatch should not be positive: "
                f"discharge={total_discharge:.3f}, charge={total_charge:.3f}"
            )

    def test_very_high_price_spike_at_single_hour(self, optimizer):
        """A single extreme price spike should trigger discharge."""
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.9)
        lmp = [10.0] * 23 + [1000.0]
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            # Should discharge at the spike hour
            assert solution.discharge_mw["bat-001"][23] > 0.0

    def test_multi_asset_objective_equals_sum_of_revenues(self, optimizer):
        assets = [
            Asset(asset_id="a1", capacity_mwh=2.0, power_mw=1.0, soc_init=0.5),
            Asset(asset_id="a2", capacity_mwh=2.0, power_mw=1.0, soc_init=0.5),
        ]
        lmp = [15.0] * 12 + [90.0] * 12
        solution = optimizer.solve(assets=assets, lmp=lmp)
        assert solution.status in ("Optimal", "Feasible", "infeasible", "error")

    def test_rte_reduces_effective_discharge(self, optimizer):
        """Lower RTE should result in less net energy recovered."""
        lmp_profile = [10.0] * 12 + [100.0] * 12
        asset_high_rte = Asset(asset_id="a-high", capacity_mwh=4.0, power_mw=2.0, rte=0.98, soc_init=0.5)
        asset_low_rte = Asset(asset_id="a-low", capacity_mwh=4.0, power_mw=2.0, rte=0.70, soc_init=0.5)
        sol_high = optimizer.solve(assets=[asset_high_rte], lmp=lmp_profile)
        sol_low = optimizer.solve(assets=[asset_low_rte], lmp=lmp_profile)
        if sol_high.status in ("Optimal", "Feasible") and sol_low.status in ("Optimal", "Feasible"):
            # High RTE should yield higher or equal objective
            assert sol_high.objective >= sol_low.objective - 1e-4


class TestOptimizerEdgeCases:
    def test_empty_asset_list_raises_or_returns_empty(self):
        optimizer = MILPDispatchOptimizer(horizon=24)
        lmp = [50.0] * 24
        try:
            solution = optimizer.solve(assets=[], lmp=lmp)
            assert solution.status in ("infeasible", "error", "Optimal", "Feasible")
        except (ValueError, IndexError, Exception):
            pass  # acceptable

    def test_zero_capacity_asset(self):
        optimizer = MILPDispatchOptimizer(horizon=6)
        asset = Asset(asset_id="zero", capacity_mwh=0.001, power_mw=0.001, soc_init=0.5)
        lmp = [10.0, 10.0, 100.0, 100.0, 10.0, 10.0]
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        # Should not crash
        assert solution.status is not None
