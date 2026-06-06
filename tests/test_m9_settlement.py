"""Settlement module (m9) tests: CAISO and ERCOT settlement engines."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from vela.m9_settlement.settlement_engine import (
    SettlementEngine,
    SettlementInterval,
    SettlementStatement,
)


@pytest.fixture
def caiso_engine() -> SettlementEngine:
    return SettlementEngine(market="CAISO")


@pytest.fixture
def ercot_engine() -> SettlementEngine:
    return SettlementEngine(market="ERCOT")


@pytest.fixture
def settlement_date() -> datetime:
    return datetime(2024, 7, 15, tzinfo=timezone.utc)


class TestSettlementEngineCAISO:
    def test_calculate_returns_statement(self, caiso_engine, settlement_date, sample_lmp):
        stmt = caiso_engine.calculate(
            asset_id="bat-001",
            settlement_date=settlement_date,
            scheduled_mwh=[1.5] * 24,
            metered_mwh=[1.5] * 24,
            lmp=sample_lmp,
        )
        assert isinstance(stmt, SettlementStatement)
        assert stmt.asset_id == "bat-001"
        assert stmt.market == "CAISO"

    def test_24_interval_statement(self, caiso_engine, settlement_date, sample_lmp):
        stmt = caiso_engine.calculate(
            asset_id="bat-001",
            settlement_date=settlement_date,
            scheduled_mwh=[2.0] * 24,
            metered_mwh=[2.0] * 24,
            lmp=sample_lmp,
        )
        assert len(stmt.intervals) == 24

    def test_energy_revenue_is_positive_for_discharge(self, caiso_engine, settlement_date):
        lmp = [55.0] * 24
        stmt = caiso_engine.calculate(
            asset_id="bat-001",
            settlement_date=settlement_date,
            scheduled_mwh=[1.0] * 24,
            metered_mwh=[1.0] * 24,
            lmp=lmp,
        )
        assert stmt.total_revenue > 0.0

    def test_zero_delivery_produces_zero_energy_revenue(self, caiso_engine, settlement_date, sample_lmp):
        stmt = caiso_engine.calculate(
            asset_id="bat-001",
            settlement_date=settlement_date,
            scheduled_mwh=[0.0] * 24,
            metered_mwh=[0.0] * 24,
            lmp=sample_lmp,
        )
        assert stmt.total_energy_mwh == pytest.approx(0.0, abs=1e-6)

    def test_overdelivery_incurs_imbalance(self, caiso_engine, settlement_date):
        scheduled = [1.0] * 24
        metered = [1.5] * 24  # 50% overdelivery
        lmp = [50.0] * 24
        stmt = caiso_engine.calculate(
            asset_id="bat-001",
            settlement_date=settlement_date,
            scheduled_mwh=scheduled,
            metered_mwh=metered,
            lmp=lmp,
        )
        assert stmt.total_imbalance_charge > 0.0

    def test_underdelivery_incurs_imbalance(self, caiso_engine, settlement_date):
        scheduled = [2.0] * 24
        metered = [1.0] * 24  # 50% underdelivery
        lmp = [50.0] * 24
        stmt = caiso_engine.calculate(
            asset_id="bat-001",
            settlement_date=settlement_date,
            scheduled_mwh=scheduled,
            metered_mwh=metered,
            lmp=lmp,
        )
        assert stmt.total_imbalance_charge > 0.0

    def test_high_lmp_yields_higher_revenue(self, caiso_engine, settlement_date):
        low_lmp = [30.0] * 24
        high_lmp = [120.0] * 24
        delivery = [1.5] * 24

        stmt_low = caiso_engine.calculate("bat-001", settlement_date, delivery, delivery, low_lmp)
        stmt_high = caiso_engine.calculate("bat-001", settlement_date, delivery, delivery, high_lmp)

        assert stmt_high.total_revenue > stmt_low.total_revenue


class TestSettlementEngineERCOT:
    def test_ercot_engine_market_name(self, ercot_engine, settlement_date):
        stmt = ercot_engine.calculate(
            asset_id="bat-ercot-001",
            settlement_date=settlement_date,
            scheduled_mwh=[1.0] * 24,
            metered_mwh=[1.0] * 24,
            lmp=[70.0] * 24,
        )
        assert stmt.market == "ERCOT"

    def test_ercot_settlement_revenue_is_positive(self, ercot_engine, settlement_date):
        stmt = ercot_engine.calculate(
            asset_id="bat-ercot-001",
            settlement_date=settlement_date,
            scheduled_mwh=[2.0] * 24,
            metered_mwh=[2.0] * 24,
            lmp=[85.0] * 24,
        )
        assert stmt.total_revenue > 0.0


class TestSettlementIntervalTimestamps:
    def test_intervals_have_sequential_timestamps(self, caiso_engine, settlement_date, sample_lmp):
        stmt = caiso_engine.calculate(
            asset_id="bat-001",
            settlement_date=settlement_date,
            scheduled_mwh=[1.0] * 24,
            metered_mwh=[1.0] * 24,
            lmp=sample_lmp,
        )
        for i in range(1, len(stmt.intervals)):
            assert stmt.intervals[i].interval_start > stmt.intervals[i - 1].interval_start
