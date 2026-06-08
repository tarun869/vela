"""Tests for m41_optimizer — heuristic dispatch engine + spike detection."""
from __future__ import annotations

from typing import Any

from vela.m39_extraction.models import DeliveryWindow, ExtractedObligation
from vela.m41_optimizer.heuristic import HeuristicOptimizer, detect_spike


def _asset(soh: float, *, rated_mw: float = 50.0, soc: float = 60.0,
           temp: float = 25.0) -> dict[str, Any]:
    return {
        "soh_pct": soh,
        "soc_pct": soc,
        "temperature_c": temp,
        "rated_mw": rated_mw,
        "rated_mwh": rated_mw * 4.0,
        "warranty_cycles": 6000,
    }


def _all_day_obligation(committed_mw: float) -> ExtractedObligation:
    return ExtractedObligation(
        obligation_type="capacity",
        committed_mw=committed_mw,
        delivery_windows=[DeliveryWindow(days=["All"], start_hour=0, end_hour=23)],
        confidence=1.0,
    )


def _by_id(plan: Any, asset_id: str) -> Any:
    return next(d for d in plan.decisions if d.asset_id == asset_id)


# --- (a) healthier asset discharges more -------------------------------------


async def test_healthier_asset_gets_higher_allocation() -> None:
    state = {"assets": {"healthy": _asset(94.0), "worn": _asset(87.0)}}
    plan = await HeuristicOptimizer().optimize(
        state, current_lmp=200.0, obligations=[], current_hour=12
    )

    healthy = _by_id(plan, "healthy")
    worn = _by_id(plan, "worn")
    assert healthy.recommended_mw > worn.recommended_mw > 0


# --- (b) obligation reserve is held back from discharge ----------------------


async def test_obligation_reserve_held_back() -> None:
    state = {"assets": {"healthy": _asset(94.0), "worn": _asset(87.0)}}
    obligations = [_all_day_obligation(30.0)]
    plan = await HeuristicOptimizer().optimize(state, 200.0, obligations, current_hour=18)

    # Reserve goes to the healthiest asset first.
    healthy = _by_id(plan, "healthy")
    assert healthy.binding_constraint == "CAPACITY_OBLIGATION"
    assert healthy.recommended_mw < healthy.unconstrained_mw

    # vs the same fleet with no obligation, the healthy asset now discharges less.
    free_plan = await HeuristicOptimizer().optimize(state, 200.0, [], current_hour=18)
    assert healthy.recommended_mw < _by_id(free_plan, "healthy").recommended_mw


# --- (c) constraint cost is non-zero when capacity is reserved ---------------


async def test_constraint_cost_nonzero_for_reservation() -> None:
    state = {"assets": {"healthy": _asset(94.0)}}
    plan = await HeuristicOptimizer().optimize(state, 200.0, [_all_day_obligation(30.0)], 18)
    healthy = _by_id(plan, "healthy")
    assert healthy.binding_constraint == "CAPACITY_OBLIGATION"
    assert healthy.constraint_cost_usd > 0.0


# --- (d/e) spike detection ---------------------------------------------------


def test_detect_spike_fires_on_large_jump() -> None:
    alert = detect_spike(current_lmp=400.0, prev_lmp=100.0)
    assert alert is not None
    assert alert.recommended_action == "DISCHARGE_FULL"
    assert alert.pct_change == 300.0


def test_detect_spike_none_for_normal_movement() -> None:
    assert detect_spike(current_lmp=120.0, prev_lmp=100.0) is None
    # High but not a sharp jump => no spike.
    assert detect_spike(current_lmp=320.0, prev_lmp=300.0) is None


# --- (f) reasoning strings contain real numbers ------------------------------


async def test_reasoning_strings_have_real_numbers() -> None:
    state = {"assets": {"healthy": _asset(94.0), "worn": _asset(72.0, temp=40.0)}}
    plan = await HeuristicOptimizer().optimize(state, 200.0, [_all_day_obligation(20.0)], 18)
    for decision in plan.decisions:
        assert "{" not in decision.reasoning  # no unfilled template placeholders
        assert any(ch.isdigit() for ch in decision.reasoning)


# --- (g) obligation status buffer logic --------------------------------------


async def test_obligation_status_covered_vs_at_risk() -> None:
    opt = HeuristicOptimizer()

    covered_state = {"assets": {"a": _asset(90.0, rated_mw=50.0)}}
    covered = await opt.optimize(covered_state, 200.0, [_all_day_obligation(30.0)], 12)
    assert covered.obligations_status[0].status == "COVERED"

    at_risk_state = {"assets": {"a": _asset(90.0, rated_mw=50.0)}}
    at_risk = await opt.optimize(at_risk_state, 200.0, [_all_day_obligation(48.0)], 12)
    assert at_risk.obligations_status[0].status == "AT_RISK"

    breached = await opt.optimize(at_risk_state, 200.0, [_all_day_obligation(80.0)], 12)
    assert breached.obligations_status[0].status == "BREACHED"
