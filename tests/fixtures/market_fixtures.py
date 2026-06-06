"""Market data test fixtures: LMP profiles, ancillary prices, bid data."""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone


@pytest.fixture
def flat_lmp() -> list[float]:
    """Flat $50/MWh LMP — baseline for testing energy neutrality."""
    return [50.0] * 24


@pytest.fixture
def peak_valley_lmp() -> list[float]:
    """Classic two-peak LMP with a morning and evening peak."""
    return [
        20.0, 18.0, 17.0, 16.0, 15.0, 18.0,  # valley (overnight)
        30.0, 55.0, 80.0, 75.0, 65.0, 60.0,  # morning peak
        58.0, 60.0, 62.0, 65.0, 80.0, 110.0,  # afternoon ramp
        140.0, 155.0, 120.0, 85.0, 55.0, 35.0,  # evening super-peak
    ]


@pytest.fixture
def spike_lmp() -> list[float]:
    """LMP with a single extreme spike at hour 19 (stress test)."""
    prices = [30.0] * 24
    prices[19] = 500.0
    return prices


@pytest.fixture
def negative_lmp() -> list[float]:
    """LMP with negative prices (curtailment periods, common in CAISO midday)."""
    prices = [40.0] * 24
    for h in range(10, 15):
        prices[h] = -15.0
    return prices


@pytest.fixture
def ancillary_prices() -> dict[str, list[float]]:
    """24-hour ancillary service price profiles."""
    return {
        "reg_up": [12.0, 11.0, 10.0, 9.0, 9.0, 11.0, 15.0, 22.0, 25.0, 23.0, 20.0, 18.0,
                   17.0, 18.0, 19.0, 21.0, 26.0, 35.0, 40.0, 42.0, 33.0, 24.0, 18.0, 14.0],
        "reg_down": [6.0, 5.5, 5.0, 5.0, 5.0, 5.5, 7.0, 10.0, 12.0, 11.0, 9.0, 8.5,
                     8.0, 8.5, 9.0, 10.0, 12.0, 16.0, 19.0, 20.0, 15.0, 11.0, 8.5, 7.0],
        "spin": [9.0, 8.5, 8.0, 7.5, 7.5, 8.5, 11.0, 17.0, 20.0, 18.0, 16.0, 14.0,
                 13.0, 14.0, 15.0, 17.0, 21.0, 28.0, 32.0, 33.0, 26.0, 19.0, 14.0, 11.0],
    }


@pytest.fixture
def market_bid_data() -> dict:
    """Sample bid data for unit tests."""
    now = datetime(2024, 7, 15, 0, 0, tzinfo=timezone.utc)
    return {
        "asset_id": "bat-001",
        "market": "CAISO",
        "service": "energy",
        "quantity_mw": 2.0,
        "price_usd_mwh": 45.0,
        "interval_start": now.isoformat(),
        "interval_end": (now + timedelta(hours=1)).isoformat(),
    }


@pytest.fixture
def historical_lmp_week() -> list[float]:
    """7 days (168 hours) of synthetic LMP data for model training."""
    import numpy as np
    np.random.seed(42)
    daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
    history = []
    for _ in range(7):
        history.extend([max(0.0, p + np.random.normal(0, 5)) for p in daily])
    return history
