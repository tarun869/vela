"""Timezone-aware datetime utilities for the Vela VPP backend."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, date
from typing import Iterator
import zoneinfo


UTC = timezone.utc


def utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


def to_utc(dt: datetime, local_tz: str | None = None) -> datetime:
    """
    Convert a datetime to UTC.
    If `dt` is naive and `local_tz` is provided, assume it is in that timezone.
    """
    if dt.tzinfo is None:
        if local_tz:
            tz = zoneinfo.ZoneInfo(local_tz)
            dt = dt.replace(tzinfo=tz)
        else:
            dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_local(dt: datetime, tz_name: str) -> datetime:
    """Convert a UTC datetime to the given local timezone."""
    tz = zoneinfo.ZoneInfo(tz_name)
    return dt.astimezone(tz)


def floor_to_hour(dt: datetime) -> datetime:
    """Truncate a datetime to the top of the hour."""
    return dt.replace(minute=0, second=0, microsecond=0)


def floor_to_interval(dt: datetime, interval_minutes: int) -> datetime:
    """Floor a datetime to the nearest `interval_minutes` boundary (e.g. 5, 15, 30)."""
    floored_min = (dt.minute // interval_minutes) * interval_minutes
    return dt.replace(minute=floored_min, second=0, microsecond=0)


def hour_range(start: datetime, end: datetime) -> Iterator[datetime]:
    """Yield hourly datetimes from start to end (inclusive of start)."""
    current = floor_to_hour(start)
    while current < end:
        yield current
        current += timedelta(hours=1)


def interval_range(start: datetime, end: datetime, interval_minutes: int) -> Iterator[datetime]:
    """Yield datetimes at `interval_minutes` increments from start to end."""
    step = timedelta(minutes=interval_minutes)
    current = floor_to_interval(start, interval_minutes)
    while current < end:
        yield current
        current += step


def trading_day_bounds(dt: datetime, tz_name: str = "America/Los_Angeles") -> tuple[datetime, datetime]:
    """
    Return the start and end of the trading day (midnight to midnight) in local time.
    CAISO day starts at 00:00 PPT (Pacific Prevailing Time).
    """
    local_dt = to_local(dt, tz_name)
    start_local = local_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return to_utc(start_local), to_utc(end_local)


def ercot_day_bounds(dt: datetime) -> tuple[datetime, datetime]:
    """ERCOT trading day bounds in Central Prevailing Time."""
    return trading_day_bounds(dt, tz_name="America/Chicago")


def is_peak_hour(dt: datetime, tz_name: str = "America/Los_Angeles") -> bool:
    """
    Return True if `dt` falls in on-peak hours (HE 8-22 local, Mon-Sat).
    Based on CAISO Time of Use definitions.
    """
    local = to_local(dt, tz_name)
    return (
        local.weekday() < 6  # Mon-Sat
        and 7 <= local.hour < 22
    )


def iso_format(dt: datetime) -> str:
    """Return ISO 8601 string with UTC 'Z' suffix."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(ts_str: str) -> datetime:
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime."""
    from datetime import datetime as _dt
    # Handle 'Z' suffix
    cleaned = ts_str.replace("Z", "+00:00")
    return _dt.fromisoformat(cleaned).astimezone(UTC)


def settlement_period(dt: datetime, lag_hours: int = 72) -> tuple[datetime, datetime]:
    """
    Return the settlement posting window for a given trading interval.
    Markets typically post final settlements 72 hours after real-time.
    """
    preliminary = dt + timedelta(hours=24)
    final = dt + timedelta(hours=lag_hours)
    return preliminary, final
