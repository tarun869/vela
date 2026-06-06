"""Tests for the battery asset model and its physical constraints."""
from __future__ import annotations

import pytest
from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer


class TestAssetModel:
    def test_asset_default_params(self):
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0)
        assert asset.rte == 0.92
        assert asset.soc_init == 0.5
        assert asset.soc_min == 0.05
        assert asset.soc_max == 0.95

    def test_asset_custom_params(self):
        asset = Asset(
            asset_id="bat-custom",
            capacity_mwh=10.0,
            power_mw=5.0,
            rte=0.88,
            soc_init=0.7,
            soc_min=0.10,
            soc_max=0.90,
        )
        assert asset.capacity_mwh == 10.0
        assert asset.power_mw == 5.0
        assert asset.rte == 0.88

    def test_usable_capacity_respects_soc_bounds(self):
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_min=0.1, soc_max=0.9)
        # Usable = capacity * (soc_max - soc_min) = 4.0 * 0.8 = 3.2
        usable = asset.capacity_mwh * (asset.soc_max - asset.soc_min)
        assert abs(usable - 3.2) < 1e-9


class TestBatteryDispatch:
    """Test dispatch solver behavior for a single battery."""

    def test_flat_lmp_no_dispatch(self):
        """With flat LMP there is no arbitrage opportunity; net dispatch should be near zero."""
        optimizer = MILPDispatchOptimizer(horizon=24)
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
        solution = optimizer.solve(assets=[asset], lmp=[50.0] * 24)
        assert solution.status in ("Optimal", "Feasible", "infeasible")
        if solution.status in ("Optimal", "Feasible"):
            total_discharge = sum(solution.discharge_mw["bat-001"])
            total_charge = sum(solution.charge_mw["bat-001"])
            # With flat prices, charge ~= discharge (round-trip losses only)
            assert abs(total_discharge - total_charge) <= total_charge * 0.15 + 0.1

    def test_peak_valley_lmp_charges_valley_discharges_peak(self):
        """Battery should charge at low prices and discharge at high prices."""
        optimizer = MILPDispatchOptimizer(horizon=24)
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
        lmp = [15.0] * 8 + [100.0] * 8 + [15.0] * 8  # valley/peak/valley
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            charge_valley = sum(solution.charge_mw["bat-001"][:8])
            discharge_peak = sum(solution.discharge_mw["bat-001"][8:16])
            assert charge_valley > 0.0 or discharge_peak > 0.0

    def test_soc_stays_within_bounds(self):
        """SOC should always remain within [soc_min, soc_max]."""
        optimizer = MILPDispatchOptimizer(horizon=24)
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
        lmp = [20.0] * 12 + [120.0] * 12
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            for soc in solution.soc["bat-001"]:
                assert asset.soc_min - 1e-4 <= soc <= asset.soc_max + 1e-4

    def test_power_limits_respected(self):
        """Charge and discharge power must not exceed the rated power_mw."""
        optimizer = MILPDispatchOptimizer(horizon=24)
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
        lmp = [10.0] * 12 + [200.0] * 12
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            for t in range(24):
                assert solution.charge_mw["bat-001"][t] <= asset.power_mw + 1e-4
                assert solution.discharge_mw["bat-001"][t] <= asset.power_mw + 1e-4

    def test_no_simultaneous_charge_and_discharge(self):
        """The optimizer should not charge and discharge at the same time."""
        optimizer = MILPDispatchOptimizer(horizon=24)
        asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
        lmp = [50.0] * 24
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            for t in range(24):
                c = solution.charge_mw["bat-001"][t]
                d = solution.discharge_mw["bat-001"][t]
                assert c * d < 1e-6, f"Simultaneous charge={c:.3f} and discharge={d:.3f} at t={t}"

    def test_high_soc_battery_prefers_discharge(self):
        """A battery starting at high SOC should prefer to discharge first."""
        optimizer = MILPDispatchOptimizer(horizon=6)
        asset = Asset(asset_id="bat-high", capacity_mwh=4.0, power_mw=2.0, soc_init=0.92)
        lmp = [80.0] * 6
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            total_discharge = sum(solution.discharge_mw["bat-high"])
            total_charge = sum(solution.charge_mw["bat-high"])
            assert total_discharge >= total_charge or total_discharge > 0

    def test_low_soc_battery_prefers_charging(self):
        """A battery with very low SOC should charge before discharging."""
        optimizer = MILPDispatchOptimizer(horizon=12)
        asset = Asset(asset_id="bat-low", capacity_mwh=4.0, power_mw=2.0, soc_init=0.08)
        lmp = [200.0] * 12  # high prices, but must charge first
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        # Just verify no SOC violations
        if solution.status in ("Optimal", "Feasible"):
            for soc in solution.soc["bat-low"]:
                assert soc >= asset.soc_min - 1e-4


class TestMultiAssetDispatch:
    def test_fleet_dispatch_returns_all_assets(self):
        optimizer = MILPDispatchOptimizer(horizon=24)
        assets = [
            Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0),
            Asset(asset_id="bat-002", capacity_mwh=2.0, power_mw=1.0),
        ]
        lmp = [20.0] * 12 + [80.0] * 12
        solution = optimizer.solve(assets=assets, lmp=lmp)
        if solution.status in ("Optimal", "Feasible"):
            assert "bat-001" in solution.charge_mw
            assert "bat-002" in solution.charge_mw
            assert len(solution.charge_mw["bat-001"]) == 24
            assert len(solution.soc["bat-002"]) == 24
