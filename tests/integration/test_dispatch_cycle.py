"""Integration test: full dispatch cycle from observe to settle."""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from vela.orchestrator.loop import DispatchLoop, LoopState


@pytest.mark.asyncio
async def test_full_dispatch_cycle_runs_to_completion():
    """Run a complete dispatch cycle and verify all phases executed without error."""
    loop = DispatchLoop(
        horizon_hours=6,  # short horizon for fast test
        market="CAISO",
        interval_seconds=1.0,
    )
    state = await loop.run_cycle()
    assert state.phase == "complete"


@pytest.mark.asyncio
async def test_dispatch_cycle_observes_assets():
    loop = DispatchLoop(horizon_hours=4)
    state = LoopState(cycle_id="test-001")
    state = await loop._phase_observe(state)
    assert len(state.asset_ids) > 0


@pytest.mark.asyncio
async def test_dispatch_cycle_generates_forecast():
    loop = DispatchLoop(horizon_hours=4)
    state = LoopState(cycle_id="test-002")
    state.asset_ids = ["bat-001"]
    state = await loop._phase_forecast(state)
    assert len(state.lmp_forecast) == 4
    assert all(v >= 0 for v in state.lmp_forecast)


@pytest.mark.asyncio
async def test_dispatch_cycle_runs_optimization():
    loop = DispatchLoop(horizon_hours=4)
    state = LoopState(cycle_id="test-003")
    state.asset_ids = ["bat-001", "bat-002"]
    state.lmp_forecast = [20.0, 20.0, 80.0, 80.0]
    state = await loop._phase_optimize(state)
    # Should have a solution or a logged error (no crash)
    assert state.phase == "optimize"


@pytest.mark.asyncio
async def test_dispatch_cycle_prepare_bids():
    from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer
    loop = DispatchLoop(horizon_hours=4)
    state = LoopState(cycle_id="test-004")
    state.asset_ids = ["bat-001"]
    state.lmp_forecast = [15.0, 15.0, 100.0, 100.0]

    # Pre-run the optimize phase to get a real solution
    asset = Asset(asset_id="bat-001", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
    optimizer = MILPDispatchOptimizer(horizon=4)
    state.dispatch_solution = optimizer.solve(assets=[asset], lmp=state.lmp_forecast)

    state = await loop._phase_bid(state)
    # Should not crash; bids may or may not be generated
    assert state.phase == "bid"


@pytest.mark.asyncio
async def test_dispatch_cycle_runs_settlement():
    loop = DispatchLoop(horizon_hours=4)
    state = LoopState(cycle_id="test-005")
    state.asset_ids = ["bat-001"]
    state.lmp_forecast = [55.0, 55.0, 55.0, 55.0]
    state = await loop._phase_settle(state)
    assert len(state.settlement_results) > 0
    assert all("asset_id" in r for r in state.settlement_results)


@pytest.mark.asyncio
async def test_dispatch_cycle_handles_empty_assets_gracefully():
    """Cycle with no assets should complete without crashing."""
    loop = DispatchLoop(horizon_hours=4)
    state = LoopState(cycle_id="test-empty")
    state = await loop._phase_observe(state)
    # Even with no assets, forecast should provide fallback values
    state.asset_ids = []
    state = await loop._phase_forecast(state)
    state = await loop._phase_optimize(state)
    assert state.phase == "optimize"


def test_dispatch_loop_stop_flag():
    loop = DispatchLoop()
    assert loop._running is False
    loop._running = True
    loop.stop()
    assert loop._running is False
