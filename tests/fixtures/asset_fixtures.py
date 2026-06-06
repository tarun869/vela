"""Asset test fixtures: battery, flywheel, pumped hydro, and fleet configurations."""
from __future__ import annotations

import pytest
from vela.m6_optimizer.milp import Asset
from vela.portfolio.models import AssetProfile


@pytest.fixture
def single_battery() -> Asset:
    return Asset(
        asset_id="bat-001",
        capacity_mwh=4.0,
        power_mw=2.0,
        rte=0.92,
        soc_init=0.5,
        soc_min=0.05,
        soc_max=0.95,
    )


@pytest.fixture
def low_soc_battery() -> Asset:
    return Asset(
        asset_id="bat-low",
        capacity_mwh=4.0,
        power_mw=2.0,
        rte=0.90,
        soc_init=0.08,
        soc_min=0.05,
        soc_max=0.95,
    )


@pytest.fixture
def high_soc_battery() -> Asset:
    return Asset(
        asset_id="bat-high",
        capacity_mwh=4.0,
        power_mw=2.0,
        rte=0.92,
        soc_init=0.92,
        soc_min=0.05,
        soc_max=0.95,
    )


@pytest.fixture
def small_battery() -> Asset:
    return Asset(
        asset_id="bat-small",
        capacity_mwh=1.0,
        power_mw=0.5,
        rte=0.90,
        soc_init=0.5,
    )


@pytest.fixture
def fleet_of_three() -> list[Asset]:
    return [
        Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5),
        Asset(asset_id="bat-002", capacity_mwh=2.0, power_mw=1.0, soc_init=0.7),
        Asset(asset_id="bat-003", capacity_mwh=8.0, power_mw=4.0, soc_init=0.3),
    ]


@pytest.fixture
def asset_profile() -> AssetProfile:
    return AssetProfile(
        asset_id="bat-001",
        asset_type="battery",
        capacity_mwh=4.0,
        power_mw=2.0,
        rte=0.92,
        iso="CAISO",
        pricing_node="TH_NP15_GEN-APND",
    )


@pytest.fixture
def degraded_battery() -> Asset:
    """Battery that has been cycled significantly, with reduced effective capacity."""
    return Asset(
        asset_id="bat-degraded",
        capacity_mwh=4.0 * 0.85,  # 15% capacity loss after heavy use
        power_mw=2.0,
        rte=0.88,  # degraded RTE
        soc_init=0.5,
        soc_min=0.10,  # raised minimum due to aging
        soc_max=0.90,
    )
