"""Grid state test fixtures: carbon intensity, grid conditions, system constraints."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone


@pytest.fixture
def clean_grid_state() -> dict:
    """High renewable penetration, low carbon intensity."""
    return {
        "region": "CAISO",
        "timestamp": datetime(2024, 7, 15, 13, 0, tzinfo=timezone.utc),
        "carbon_intensity_kg_per_mwh": 85.0,
        "renewable_pct": 0.72,
        "solar_mw": 12000.0,
        "wind_mw": 3500.0,
        "load_mw": 28000.0,
        "reserve_margin": 0.20,
        "frequency_hz": 60.0,
        "voltage_pu": 1.01,
    }


@pytest.fixture
def stressed_grid_state() -> dict:
    """High load, low renewable generation, stressed conditions."""
    return {
        "region": "CAISO",
        "timestamp": datetime(2024, 7, 15, 19, 0, tzinfo=timezone.utc),
        "carbon_intensity_kg_per_mwh": 480.0,
        "renewable_pct": 0.18,
        "solar_mw": 800.0,
        "wind_mw": 1200.0,
        "load_mw": 46000.0,
        "reserve_margin": 0.07,  # below 15% threshold
        "frequency_hz": 59.97,  # slightly low
        "voltage_pu": 0.97,
    }


@pytest.fixture
def curtailment_grid_state() -> dict:
    """Midday solar surplus causing negative LMPs and curtailment."""
    return {
        "region": "CAISO",
        "timestamp": datetime(2024, 7, 15, 12, 0, tzinfo=timezone.utc),
        "carbon_intensity_kg_per_mwh": 40.0,
        "renewable_pct": 0.95,
        "solar_mw": 18000.0,
        "wind_mw": 5000.0,
        "load_mw": 22000.0,
        "reserve_margin": 0.38,
        "frequency_hz": 60.05,
        "voltage_pu": 1.03,
        "curtailment_mw": 1800.0,  # active curtailment
    }


@pytest.fixture
def grid_constraints() -> dict:
    """Typical operating constraints for the CAISO system."""
    return {
        "frequency_min_hz": 59.95,
        "frequency_max_hz": 60.05,
        "voltage_min_pu": 0.95,
        "voltage_max_pu": 1.05,
        "reserve_margin_min": 0.15,
        "max_ramp_mw_per_min": 5.0,
        "min_online_capacity_mw": 500.0,
    }
