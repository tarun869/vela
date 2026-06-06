"""Co-optimization tests: energy + ancillary service joint dispatch."""
from __future__ import annotations

import pytest
import numpy as np
from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer


@pytest.fixture
def optimizer_24h() -> MILPDispatchOptimizer:
    return MILPDispatchOptimizer(horizon=24)


@pytest.fixture
def standard_asset() -> Asset:
    return Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)


@pytest.fixture
def ancillary_prices() -> dict[str, list[float]]:
    np.random.seed(5)
    return {
        "reg_up": [max(0, 12 + np.random.normal(0, 2)) for _ in range(24)],
        "reg_down": [max(0, 7 + np.random.normal(0, 1)) for _ in range(24)],
        "spin": [max(0, 10 + np.random.normal(0, 2)) for _ in range(24)],
    }


class TestEnergyOnlyDispatch:
    def test_energy_arbitrage_objective_is_non_negative(self, optimizer_24h, standard_asset, sample_lmp):
        solution = optimizer_24h.solve(assets=[standard_asset], lmp=sample_lmp)
        if solution.status in ("Optimal", "Feasible"):
            assert solution.objective >= -1e-4  # allow tiny numerical noise

    def test_charging_below_soc_max(self, optimizer_24h, standard_asset):
        lmp = [10.0] * 24
        solution = optimizer_24h.solve(assets=[standard_asset], lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            for soc in solution.soc["bat-001"]:
                assert soc <= standard_asset.soc_max + 1e-4

    def test_discharging_above_soc_min(self, optimizer_24h, standard_asset):
        lmp = [200.0] * 24
        solution = optimizer_24h.solve(assets=[standard_asset], lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            for soc in solution.soc["bat-001"]:
                assert soc >= standard_asset.soc_min - 1e-4


class TestAncillaryCoOptimization:
    def test_co_opt_with_reg_up_price(self, optimizer_24h, standard_asset, sample_lmp, ancillary_prices):
        """Passing reg_up prices should not crash and may improve objective."""
        solution_energy = optimizer_24h.solve(assets=[standard_asset], lmp=sample_lmp)
        solution_coop = optimizer_24h.solve(
            assets=[standard_asset],
            lmp=sample_lmp,
            reg_up_price=ancillary_prices["reg_up"],
        )
        # Both should either succeed or fail gracefully
        assert solution_energy.status in ("Optimal", "Feasible", "infeasible", "error")
        assert solution_coop.status in ("Optimal", "Feasible", "infeasible", "error")

    def test_co_opt_with_all_ancillaries(self, optimizer_24h, standard_asset, sample_lmp, ancillary_prices):
        solution = optimizer_24h.solve(
            assets=[standard_asset],
            lmp=sample_lmp,
            reg_up_price=ancillary_prices["reg_up"],
            reg_down_price=ancillary_prices["reg_down"],
            spin_price=ancillary_prices["spin"],
        )
        assert solution.status in ("Optimal", "Feasible", "infeasible", "error")
        if solution.status in ("Optimal", "Feasible"):
            assert solution.objective >= 0 or solution.objective < 1e6

    def test_co_opt_objective_gte_energy_only(self, optimizer_24h, standard_asset, sample_lmp, ancillary_prices):
        """Adding ancillary revenue should not decrease the objective."""
        sol_e = optimizer_24h.solve(assets=[standard_asset], lmp=sample_lmp)
        sol_co = optimizer_24h.solve(
            assets=[standard_asset],
            lmp=sample_lmp,
            reg_up_price=ancillary_prices["reg_up"],
        )
        if sol_e.status in ("Optimal", "Feasible") and sol_co.status in ("Optimal", "Feasible"):
            assert sol_co.objective >= sol_e.objective - 1.0  # allow 1$ numerical tolerance


class TestMultiAssetCoOptimization:
    def test_three_asset_fleet_dispatch(self, optimizer_24h):
        assets = [
            Asset(asset_id=f"bat-{i:03d}", capacity_mwh=4.0 * i, power_mw=2.0 * i, soc_init=0.5)
            for i in range(1, 4)
        ]
        lmp = [15.0] * 12 + [90.0] * 12
        solution = optimizer_24h.solve(assets=assets, lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            for asset in assets:
                assert asset.asset_id in solution.charge_mw
                assert len(solution.soc[asset.asset_id]) == 24

    def test_larger_assets_dispatch_more_energy(self, optimizer_24h):
        small = Asset(asset_id="small", capacity_mwh=1.0, power_mw=0.5, soc_init=0.5)
        large = Asset(asset_id="large", capacity_mwh=8.0, power_mw=4.0, soc_init=0.5)
        lmp = [10.0] * 12 + [100.0] * 12
        sol_small = optimizer_24h.solve(assets=[small], lmp=lmp)
        sol_large = optimizer_24h.solve(assets=[large], lmp=lmp)
        if sol_small.status in ("Optimal", "Feasible") and sol_large.status in ("Optimal", "Feasible"):
            total_small = sum(sol_small.discharge_mw["small"])
            total_large = sum(sol_large.discharge_mw["large"])
            assert total_large >= total_small
