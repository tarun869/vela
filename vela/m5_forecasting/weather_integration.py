"""Weather API integration for forecast models."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from urllib.parse import urlencode
from urllib.request import urlopen, Request
import json

logger = logging.getLogger(__name__)


class WeatherObservation(NamedTuple):
    timestamp: datetime
    temperature_f: float
    humidity_pct: float
    wind_mph: float
    cloud_cover_pct: float
    precipitation_in: float
    solar_radiation_wm2: float


@dataclass
class WeatherForecastPoint:
    timestamp: datetime
    temperature_f: float
    humidity_pct: float
    wind_mph: float
    cloud_cover_pct: float        # 0-100
    precipitation_prob: float     # 0-1
    solar_radiation_wm2: float = 0.0


@dataclass
class NWPSource:
    """
    Numerical Weather Prediction source configuration.

    Supports Open-Meteo (free, no API key required) and
    configurable fallback to synthetic data for testing.
    """
    latitude: float
    longitude: float
    source: str = "open-meteo"
    timeout_s: int = 10
    _cache: dict[str, list[WeatherForecastPoint]] = field(
        default_factory=dict, init=False, repr=False
    )

    def fetch_hourly_forecast(
        self,
        start_utc: datetime,
        hours: int = 48,
    ) -> list[WeatherForecastPoint]:
        """
        Fetch hourly NWP forecast from Open-Meteo API.

        Falls back to synthetic clear-sky + climatology if network unavailable.
        """
        cache_key = f"{start_utc.date()}_{hours}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            points = self._fetch_open_meteo(start_utc, hours)
        except Exception as exc:
            logger.warning("Weather API fetch failed (%s), using synthetic fallback", exc)
            points = self._synthetic_forecast(start_utc, hours)

        self._cache[cache_key] = points
        return points

    def _fetch_open_meteo(
        self,
        start_utc: datetime,
        hours: int,
    ) -> list[WeatherForecastPoint]:
        """Call Open-Meteo forecast API (https://open-meteo.com/)."""
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": ",".join([
                "temperature_2m",
                "relativehumidity_2m",
                "windspeed_10m",
                "cloudcover",
                "precipitation_probability",
                "shortwave_radiation",
            ]),
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "forecast_days": max(2, math.ceil(hours / 24)),
            "timezone": "UTC",
        }
        url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
        req = Request(url, headers={"User-Agent": "VelaVPP/1.0"})
        with urlopen(req, timeout=self.timeout_s) as resp:
            data = json.loads(resp.read())

        hourly = data["hourly"]
        times = hourly["time"]
        points = []
        for i, t_str in enumerate(times[:hours]):
            ts = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
            points.append(WeatherForecastPoint(
                timestamp=ts,
                temperature_f=float(hourly["temperature_2m"][i] or 60.0),
                humidity_pct=float(hourly["relativehumidity_2m"][i] or 50.0),
                wind_mph=float(hourly["windspeed_10m"][i] or 5.0),
                cloud_cover_pct=float(hourly["cloudcover"][i] or 20.0),
                precipitation_prob=float((hourly["precipitation_probability"][i] or 0)) / 100.0,
                solar_radiation_wm2=float(hourly["shortwave_radiation"][i] or 0.0),
            ))
        return points

    def _synthetic_forecast(
        self,
        start_utc: datetime,
        hours: int,
    ) -> list[WeatherForecastPoint]:
        """Generate synthetic weather forecast for testing/fallback."""
        import numpy as np
        rng = np.random.default_rng(int(start_utc.timestamp()) % (2**32))
        points = []
        doy = start_utc.timetuple().tm_yday
        # Seasonal base temperature
        base_temp_f = 55 + 30 * math.sin(2 * math.pi * (doy - 80) / 365)

        for i in range(hours):
            dt = start_utc + timedelta(hours=i)
            hour = dt.hour
            # Diurnal temperature swing ±10°F
            diurnal = 10 * math.sin(2 * math.pi * (hour - 6) / 24)
            temp_f = base_temp_f + diurnal + 2 * float(rng.standard_normal())
            humidity = 50 + 20 * float(rng.standard_normal())
            cloud = float(np.clip(20 + 30 * rng.standard_normal(), 0, 100))
            # Clear-sky solar
            lat_rad = math.radians(self.latitude)
            delta = math.radians(23.45 * math.sin(2 * math.pi * (doy - 80) / 365))
            ha = math.radians(15 * (hour - 12))
            cos_sza = max(0, math.sin(lat_rad) * math.sin(delta) + math.cos(lat_rad) * math.cos(delta) * math.cos(ha))
            ghi_cs = 900 * cos_sza
            ghi_actual = ghi_cs * (1 - 0.75 * (cloud / 100) ** 3.4)

            points.append(WeatherForecastPoint(
                timestamp=dt,
                temperature_f=float(temp_f),
                humidity_pct=float(max(20, min(95, humidity))),
                wind_mph=float(max(0, 8 + 5 * float(rng.standard_normal()))),
                cloud_cover_pct=cloud,
                precipitation_prob=float(cloud / 200),
                solar_radiation_wm2=float(ghi_actual),
            ))
        return points


def temperature_to_celsius(temp_f: float) -> float:
    return (temp_f - 32) * 5 / 9


def celsius_to_fahrenheit(temp_c: float) -> float:
    return temp_c * 9 / 5 + 32


def compute_dew_point_f(temp_f: float, rh_pct: float) -> float:
    """Magnus formula dew point approximation."""
    tc = temperature_to_celsius(temp_f)
    a, b = 17.27, 237.7
    gamma = (a * tc / (b + tc)) + math.log(rh_pct / 100.0)
    dp_c = b * gamma / (a - gamma)
    return celsius_to_fahrenheit(dp_c)


def wind_chill_f(temp_f: float, wind_mph: float) -> float:
    """NWS wind chill formula (valid for T <= 50°F and wind > 3 mph)."""
    if temp_f > 50 or wind_mph < 3:
        return temp_f
    return (
        35.74
        + 0.6215 * temp_f
        - 35.75 * wind_mph ** 0.16
        + 0.4275 * temp_f * wind_mph ** 0.16
    )
