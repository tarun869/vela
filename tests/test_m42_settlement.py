"""Tests for m42_settlement — settlement tracking and P&L computation."""
from __future__ import annotations

from vela.m39_extraction.models import DeliveryWindow, ExtractedObligation
from vela.m41_optimizer.heuristic import INTERVAL_HOURS
from vela.m41_optimizer.models import DispatchDecision
from vela.m42_settlement.tracker import SettlementTracker


def _decision(asset_id: str, mw: float) -> DispatchDecision:
    return DispatchDecision(
        asset_id=asset_id,
        recommended_mw=mw,
        reasoning="test",
        binding_constraint=None,
        constraint_cost_usd=0.0,
        unconstrained_mw=mw,
        revenue_expected_usd=0.0,
    )


def _capacity_obligation(committed_mw: float, penalty_rate: float = 0.0) -> ExtractedObligation:
    return ExtractedObligation(
        obligation_type="capacity",
        committed_mw=committed_mw,
        delivery_windows=[DeliveryWindow(days=["All"], start_hour=0, end_hour=23)],
        penalty_linear_per_mwh=penalty_rate,
        confidence=1.0,
    )


# --- (a) revenue calculation -------------------------------------------------


def test_revenue_calculation_correct() -> None:
    tracker = SettlementTracker()
    tracker.record_dispatch(_decision("a1", 10.0), lmp=200.0, rated_mwh=40.0)
    record = tracker.dispatch_records[0]

    expected_revenue = 10.0 * 200.0 * INTERVAL_HOURS
    # 10 MW × $200/MWh × (5/60 h) = $166.67
    assert abs(record.revenue_usd - 166.6667) < 0.01
    assert abs(record.revenue_usd - expected_revenue) < 0.01


# --- (b) compliant when delivered >= committed -------------------------------


def test_obligation_compliant_when_delivered_meets_commitment() -> None:
    tracker = SettlementTracker()
    obligation = _capacity_obligation(committed_mw=10.0, penalty_rate=500.0)
    tracker.record_obligation_window(obligation, delivered_mw=10.0)
    tracker.record_obligation_window(obligation, delivered_mw=15.0)

    for rec in tracker._obligation_records.values():
        assert rec.compliant is True
        assert rec.penalty_usd == 0.0


# --- (c) penalty when delivered < committed ----------------------------------


def test_penalty_when_shortfall() -> None:
    tracker = SettlementTracker()
    obligation = _capacity_obligation(committed_mw=10.0, penalty_rate=1_000.0)
    tracker.record_obligation_window(obligation, delivered_mw=8.0)

    rec = next(iter(tracker._obligation_records.values()))
    assert rec.compliant is False
    assert abs(rec.penalty_usd - 2_000.0) < 0.01   # shortfall=2 MW × $1000/MWh


# --- (d) baseline lower than optimizer on spike day --------------------------


def test_baseline_lower_than_optimizer_on_spike_day() -> None:
    # Fleet of 10 MW. Optimizer dispatched only during a $600 spike (3 intervals).
    # Baseline has to contend with 10 cheap ($30) intervals where it charges at cost.
    tracker = SettlementTracker(fleet_capacity_mw=10.0)

    for _ in range(3):
        tracker.record_price_tick(600.0)
        tracker.record_dispatch(
            _decision("bess", 10.0),
            lmp=600.0,
            rated_mwh=200.0,
            warranty_cycles=6000,
            soh_pct=100.0,
        )

    # Record the cheap intervals that the optimizer held through.
    for _ in range(10):
        tracker.record_price_tick(30.0)

    summary = tracker.generate_summary()

    # Optimizer net > baseline because baseline incurs charging costs at $30.
    assert summary.outperformance_usd > 0.0
    assert summary.net_value_usd > summary.baseline_revenue_usd


# --- (e) all_obligations_compliant False when any penalty > 0 ----------------


def test_all_obligations_compliant_false_if_any_penalty() -> None:
    tracker = SettlementTracker()
    compliant_obl = _capacity_obligation(committed_mw=5.0, penalty_rate=1_000.0)
    penalty_obl = _capacity_obligation(committed_mw=10.0, penalty_rate=1_000.0)

    tracker.record_obligation_window(compliant_obl, delivered_mw=5.0)   # compliant
    tracker.record_obligation_window(penalty_obl, delivered_mw=8.0)     # shortfall

    summary = tracker.generate_summary()
    assert summary.all_obligations_compliant is False
    assert summary.total_penalties_usd > 0.0
