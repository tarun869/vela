"""Settlement engine unit tests."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from vela.m9_settlement.settlement_engine import (
    SettlementEngine,
    SettlementInterval,
    SettlementStatement,
)


@pytest.fixture
def engine() -> SettlementEngine:
    return SettlementEngine(market="CAISO")


@pytest.fixture
def settlement_date() -> datetime:
    return datetime(2024, 7, 15, tzinfo=timezone.utc)


class TestSettlementInterval:
    def test_perfect_delivery_no_imbalance_charge(self):
        interval = SettlementInterval(
            interval_start=datetime(2024, 7, 15, 0, 0, tzinfo=timezone.utc),
            scheduled_mwh=2.0,
            metered_mwh=2.0,
            lmp=55.0,
        )
        assert interval.imbalance_charge == pytest.approx(0.0, abs=1e-6)
        assert interval.revenue == pytest.approx(2.0 * 55.0, abs=1e-6)

    def test_overdelivery_incurs_imbalance_charge(self):
        interval = SettlementInterval(
            interval_start=datetime(2024, 7, 15, 0, 0, tzinfo=timezone.utc),
            scheduled_mwh=1.0,
            metered_mwh=1.5,
            lmp=60.0,
        )
        assert interval.imbalance_charge > 0.0

    def test_underdelivery_incurs_imbalance_charge(self):
        interval = SettlementInterval(
            interval_start=datetime(2024, 7, 15, 0, 0, tzinfo=timezone.utc),
            scheduled_mwh=2.0,
            metered_mwh=1.5,
            lmp=60.0,
        )
        assert interval.imbalance_charge > 0.0

    def test_revenue_equals_metered_times_lmp_minus_charge(self):
        interval = SettlementInterval(
            interval_start=datetime(2024, 7, 15, 0, 0, tzinfo=timezone.utc),
            scheduled_mwh=2.0,
            metered_mwh=1.8,
            lmp=75.0,
        )
        expected = 1.8 * 75.0 - interval.imbalance_charge
        assert interval.revenue == pytest.approx(expected, abs=1e-6)


class TestSettlementStatement:
    def test_total_revenue_sums_intervals(self):
        now = datetime(2024, 7, 15, tzinfo=timezone.utc)
        intervals = [
            SettlementInterval(interval_start=now, scheduled_mwh=2.0, metered_mwh=2.0, lmp=50.0),
            SettlementInterval(interval_start=now, scheduled_mwh=2.0, metered_mwh=2.0, lmp=80.0),
        ]
        stmt = SettlementStatement(asset_id="bat-001", market="CAISO", settlement_date=now, intervals=intervals)
        assert stmt.total_revenue == pytest.approx(
            sum(i.revenue for i in intervals), abs=1e-6
        )

    def test_total_energy_sums_metered(self):
        now = datetime(2024, 7, 15, tzinfo=timezone.utc)
        intervals = [
            SettlementInterval(interval_start=now, scheduled_mwh=1.5, metered_mwh=1.5, lmp=50.0),
            SettlementInterval(interval_start=now, scheduled_mwh=1.5, metered_mwh=1.8, lmp=50.0),
        ]
        stmt = SettlementStatement(asset_id="bat-001", market="CAISO", settlement_date=now, intervals=intervals)
        assert stmt.total_energy_mwh == pytest.approx(1.5 + 1.8, abs=1e-6)

    def test_empty_intervals(self):
        now = datetime(2024, 7, 15, tzinfo=timezone.utc)
        stmt = SettlementStatement(asset_id="bat-001", market="CAISO", settlement_date=now)
        assert stmt.total_revenue == 0.0
        assert stmt.total_energy_mwh == 0.0


class TestSettlementEngine:
    def test_calculate_24_hour_statement(self, engine, settlement_date, sample_lmp):
        scheduled = [1.5] * 24
        metered = [1.5] * 24  # perfect delivery
        statement = engine.calculate(
            asset_id="bat-001",
            settlement_date=settlement_date,
            scheduled_mwh=scheduled,
            metered_mwh=metered,
            lmp=sample_lmp,
        )
        assert statement.asset_id == "bat-001"
        assert len(statement.intervals) == 24
        assert statement.total_energy_mwh == pytest.approx(36.0, abs=1e-3)

    def test_perfect_delivery_maximizes_revenue(self, engine, settlement_date, sample_lmp):
        """Perfect delivery should yield higher revenue than underdelivery."""
        scheduled = [1.5] * 24
        perfect = [1.5] * 24
        under = [1.0] * 24

        stmt_perfect = engine.calculate(
            asset_id="bat-001", settlement_date=settlement_date,
            scheduled_mwh=scheduled, metered_mwh=perfect, lmp=sample_lmp,
        )
        stmt_under = engine.calculate(
            asset_id="bat-001", settlement_date=settlement_date,
            scheduled_mwh=scheduled, metered_mwh=under, lmp=sample_lmp,
        )
        assert stmt_perfect.total_revenue > stmt_under.total_revenue

    def test_market_name_stored_in_statement(self, engine, settlement_date, sample_lmp):
        stmt = engine.calculate(
            asset_id="bat-001",
            settlement_date=settlement_date,
            scheduled_mwh=[1.0] * 24,
            metered_mwh=[1.0] * 24,
            lmp=sample_lmp,
        )
        assert stmt.market == "CAISO"

    def test_single_interval_settlement(self, engine, settlement_date):
        stmt = engine.calculate(
            asset_id="bat-001",
            settlement_date=settlement_date,
            scheduled_mwh=[2.0],
            metered_mwh=[2.0],
            lmp=[100.0],
        )
        assert stmt.total_revenue == pytest.approx(200.0, abs=1e-3)
        assert stmt.total_imbalance_charge == pytest.approx(0.0, abs=1e-3)
