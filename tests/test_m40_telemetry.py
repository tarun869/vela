"""Tests for m40_telemetry — simulators, price replay, fleet manager, WebSocket."""
from __future__ import annotations

import random
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from vela.api.app import create_app
from vela.m39_extraction.models import ExtractedAsset
from vela.m40_telemetry import api as telemetry_api
from vela.m40_telemetry.fleet_manager import FleetManager
from vela.m40_telemetry.models import PriceTick
from vela.m40_telemetry.price_feed import ERCOTHistoricalReplay
from vela.m40_telemetry.simulator import BESSSimulator, SolarSimulator


def _fixed_clock(hour: int):  # type: ignore[no-untyped-def]
    return lambda: datetime(2024, 1, 1, hour, 0, tzinfo=timezone.utc)


async def _collect(connector, n: int):  # type: ignore[no-untyped-def]
    out = []
    async for telemetry in connector.stream():
        out.append(telemetry)
        if len(out) >= n:
            break
    return out


# --- (a) SOC decreases under discharge ---------------------------------------


async def test_bess_soc_decreases_under_discharge() -> None:
    sim = BESSSimulator(
        "bess-a", rated_mw=10.0, rated_mwh=40.0, tick_interval_seconds=300.0, real_time=False
    )
    await sim.send_dispatch(5.0)  # discharge
    socs = [t.soc_pct for t in await _collect(sim, 10)]
    assert socs[-1] < socs[0]


# --- (b) SOC stays within [5%, 98%] ------------------------------------------


async def test_bess_soc_bounds_respected() -> None:
    sim = BESSSimulator(
        "bess-b", rated_mw=50.0, rated_mwh=50.0, tick_interval_seconds=600.0, real_time=False
    )
    await sim.send_dispatch(50.0)  # hard discharge -> should clamp at 5%
    low = [t.soc_pct for t in await _collect(sim, 40)]
    await sim.send_dispatch(-50.0)  # hard charge -> should clamp at 98%
    high = [t.soc_pct for t in await _collect(sim, 60)]
    for soc in low + high:
        assert 5.0 <= soc <= 98.0


# --- (c) THERMAL_WARNING fires above 38C -------------------------------------


async def test_bess_thermal_warning_fires() -> None:
    # High power on a 50 MW asset => |P|*0.9 ~ 36 over ambient => well past 38C.
    sim = BESSSimulator(
        "bess-c", rated_mw=50.0, rated_mwh=400.0, tick_interval_seconds=60.0, real_time=False
    )
    await sim.send_dispatch(45.0)
    samples = await _collect(sim, 10)
    assert any(t.alarm == "THERMAL_WARNING" for t in samples)
    assert all(t.temperature_c > 38.0 for t in samples)


# --- (d) SOH degrades faster for NMC than LFP --------------------------------


async def test_soh_nmc_degrades_faster_than_lfp() -> None:
    def make(chem: str) -> BESSSimulator:
        return BESSSimulator(
            f"bess-{chem}",
            rated_mw=50.0,
            rated_mwh=200.0,
            chemistry=chem,
            tick_interval_seconds=3600.0,
            real_time=False,
        )

    lfp, nmc = make("LFP"), make("NMC")
    await lfp.send_dispatch(50.0)
    await nmc.send_dispatch(50.0)
    lfp_soh = (await _collect(lfp, 10))[-1].soh_pct
    nmc_soh = (await _collect(nmc, 10))[-1].soh_pct
    assert nmc_soh < lfp_soh < 94.0


# --- (e/f) Solar generation profile ------------------------------------------


async def test_solar_zero_at_night() -> None:
    sim = SolarSimulator("solar-1", rated_mw=20.0, real_time=False, clock=_fixed_clock(3))
    samples = await _collect(sim, 3)
    assert all(t.power_mw == 0.0 for t in samples)


async def test_solar_generates_at_noon() -> None:
    sim = SolarSimulator(
        "solar-2", rated_mw=20.0, real_time=False, clock=_fixed_clock(12), rng=random.Random(1)
    )
    samples = await _collect(sim, 3)
    assert all(t.power_mw > 0.0 for t in samples)


# --- (g/h) ERCOT historical replay -------------------------------------------


def test_ercot_fixture_loads_priceticks() -> None:
    replay = ERCOTHistoricalReplay(date="2023-08-10", node="HB_HUBZONE")
    ticks = replay.load_ticks()
    assert len(ticks) == 96
    assert all(isinstance(t, PriceTick) for t in ticks)
    assert all(t.interval_type == "historical_replay" for t in ticks)


def test_ercot_fixture_contains_spike() -> None:
    replay = ERCOTHistoricalReplay(date="2023-08-10", node="HB_HUBZONE")
    ticks = replay.load_ticks()
    assert max(t.lmp_per_mwh for t in ticks) > 500.0


async def test_ercot_replay_streams_ticks() -> None:
    replay = ERCOTHistoricalReplay(date="2024-02-15", speed_multiplier=1e6)
    out = []
    async for tick in replay.stream():
        out.append(tick)
        if len(out) >= 5:
            break
    assert len(out) == 5
    assert all(isinstance(t, PriceTick) for t in out)


# --- (i) from_demo_fleet -----------------------------------------------------


def test_from_demo_fleet_creates_one_connector_per_asset() -> None:
    assets = [
        ExtractedAsset(asset_id="BESS-001", asset_type="BESS", rated_mw=50.0,
                       rated_mwh=200.0, chemistry="LFP", confidence=0.95),
        ExtractedAsset(asset_id="SOLAR-014", asset_type="Solar", rated_mw=25.0, confidence=0.9),
    ]
    fleet = FleetManager.from_demo_fleet(assets)
    assert len(fleet.connectors) == 2
    assert isinstance(fleet.connectors["BESS-001"], BESSSimulator)
    assert isinstance(fleet.connectors["SOLAR-014"], SolarSimulator)


# --- (j) WebSocket telemetry -------------------------------------------------


def test_websocket_streams_telemetry() -> None:
    app = create_app()
    client = TestClient(app)
    try:
        resp = client.post(
            "/api/v1/fleet/demo",
            json=[{"asset_id": "BESS-001", "asset_type": "BESS",
                   "rated_mw": 50.0, "rated_mwh": 200.0, "chemistry": "LFP"}],
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

        with client.websocket_connect("/ws/fleet/telemetry") as ws:
            seen_types = set()
            for _ in range(5):
                msg = ws.receive_json()
                seen_types.add(msg["type"])
                if "telemetry" in seen_types:
                    break
            assert "telemetry" in seen_types
    finally:
        telemetry_api.set_fleet(None)
