"""Pytest configuration and fixtures."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone


@pytest.fixture
def sample_lmp() -> list[float]:
    """24-hour LMP profile typical for CAISO."""
    return [
        25.0, 22.0, 20.0, 18.0, 17.0, 19.0,  # midnight-5am
        28.0, 45.0, 62.0, 58.0, 52.0, 48.0,  # 6am-11am
        50.0, 53.0, 55.0, 58.0, 72.0, 95.0,  # noon-5pm
        110.0, 125.0, 98.0, 75.0, 55.0, 38.0,  # 6pm-11pm
    ]


@pytest.fixture
def sample_timestamps() -> list[datetime]:
    from datetime import timedelta
    base = datetime(2024, 7, 15, 0, 0, tzinfo=timezone.utc)
    return [base + timedelta(hours=i) for i in range(24)]
