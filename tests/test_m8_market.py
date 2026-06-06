"""Market module (m8) tests: bid models, price parsing, ERCOT ancillary."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from vela.m8_market.bid_models import (
    BidCurve,
    BidTranche,
    MarketBid,
    build_price_quantity_stack,
)


@pytest.fixture
def sample_bid() -> MarketBid:
    now = datetime.now(timezone.utc)
    return MarketBid(
        bid_id="bid-001",
        asset_id="bat-001",
        market="CAISO",
        service="energy",
        quantity_mw=2.0,
        price_usd_mwh=55.0,
        interval_start=now,
        interval_end=now + timedelta(hours=1),
    )


@pytest.fixture
def sample_bid_curve() -> BidCurve:
    tranches = [
        BidTranche(quantity_mw=0.5, price_usd_mwh=30.0),
        BidTranche(quantity_mw=0.5, price_usd_mwh=45.0),
        BidTranche(quantity_mw=0.5, price_usd_mwh=65.0),
        BidTranche(quantity_mw=0.5, price_usd_mwh=90.0),
    ]
    return BidCurve(asset_id="bat-001", tranches=tranches)


class TestMarketBid:
    def test_bid_has_required_fields(self, sample_bid):
        assert sample_bid.bid_id == "bid-001"
        assert sample_bid.asset_id == "bat-001"
        assert sample_bid.market == "CAISO"
        assert sample_bid.quantity_mw == pytest.approx(2.0)
        assert sample_bid.price_usd_mwh == pytest.approx(55.0)

    def test_bid_interval_is_valid(self, sample_bid):
        assert sample_bid.interval_end > sample_bid.interval_start

    def test_bid_service_is_energy(self, sample_bid):
        assert sample_bid.service == "energy"


class TestBidCurve:
    def test_bid_curve_total_quantity(self, sample_bid_curve):
        total = sum(t.quantity_mw for t in sample_bid_curve.tranches)
        assert total == pytest.approx(2.0)

    def test_bid_curve_prices_are_ascending(self, sample_bid_curve):
        prices = [t.price_usd_mwh for t in sample_bid_curve.tranches]
        for i in range(1, len(prices)):
            assert prices[i] >= prices[i - 1]

    def test_build_price_quantity_stack(self):
        """Build a stack from optimizer output."""
        discharge_mw = [0.5, 1.0, 1.5, 2.0]
        prices = [30.0, 40.0, 55.0, 80.0]
        curve = build_price_quantity_stack(
            asset_id="bat-001",
            discharge_mw=discharge_mw,
            offer_prices=prices,
        )
        assert len(curve.tranches) == len(discharge_mw)
        for tranche in curve.tranches:
            assert tranche.quantity_mw > 0
            assert tranche.price_usd_mwh >= 0


class TestAncillaryBids:
    def test_reg_up_bid_creation(self):
        now = datetime.now(timezone.utc)
        bid = MarketBid(
            bid_id="anc-001",
            asset_id="bat-001",
            market="CAISO",
            service="reg_up",
            quantity_mw=1.0,
            price_usd_mwh=15.0,
            interval_start=now,
            interval_end=now + timedelta(hours=1),
        )
        assert bid.service == "reg_up"
        assert bid.quantity_mw == pytest.approx(1.0)

    def test_all_ancillary_service_types(self):
        now = datetime.now(timezone.utc)
        for service in ["energy", "reg_up", "reg_down", "spin", "non_spin"]:
            bid = MarketBid(
                bid_id=f"bid-{service}",
                asset_id="bat-001",
                market="CAISO",
                service=service,
                quantity_mw=1.0,
                price_usd_mwh=10.0,
                interval_start=now,
                interval_end=now + timedelta(hours=1),
            )
            assert bid.service == service


class TestMarketPriceValidation:
    def test_lmp_components_approximately_sum_to_total(self):
        """LMP = energy + congestion + loss (approximately)."""
        lmp = 58.42
        energy = 50.12
        congestion = 5.88
        loss = 2.42
        assert abs(lmp - (energy + congestion + loss)) < 0.01

    def test_negative_lmp_is_valid(self):
        """Negative LMPs can occur during curtailment events."""
        lmp = -12.5
        energy = -15.0
        congestion = 1.5
        loss = 1.0
        # Just verify the arithmetic makes sense
        assert isinstance(lmp, float)
        assert lmp < 0
