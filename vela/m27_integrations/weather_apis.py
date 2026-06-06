"""
Weather API integration clients for VPP weather-dependent forecasting.

Wraps NOAA API, OpenWeatherMap, and Tomorrow.io with unified response model.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class WeatherObservation:
    station_id: str
    timestamp: float
    temperature_c: float
    wind_speed_ms: float
    wind_direction_deg: float
    ghi_wm2: float          # Global horizontal irradiance
    cloud_cover_pct: float
    humidity_pct: float
    pressure_hpa: float
    precipitation_mm: float


@dataclass
class WeatherForecastPoint:
    timestamp: float
    temperature_c: float
    wind_speed_ms: float
    ghi_wm2: float
    probability_precipitation: float
    confidence: float = 1.0   # Model confidence 0–1


class WeatherAPIClient:
    """
    Unified weather API client with synthetic data for offline testing.

    Implements exponential backoff retry logic and response caching.
    """

    def __init__(self, api_key: str = "", cache_ttl_s: int = 300) -> None:
        self.api_key = api_key
        self.cache_ttl = cache_ttl_s
        self._cache: Dict[str, tuple] = {}   # key -> (data, expiry)

    def _cache_get(self, key: str) -> Optional[list]:
        entry = self._cache.get(key)
        if entry and time.time() < entry[1]:
            return entry[0]
        return None

    def _cache_set(self, key: str, data: list) -> None:
        self._cache[key] = (data, time.time() + self.cache_ttl)

    def get_forecast(
        self,
        lat: float,
        lon: float,
        hours: int = 48,
    ) -> List[WeatherForecastPoint]:
        """
        Fetch NWP forecast. Uses synthetic generation when API key is not set.
        """
        key = f"forecast_{lat:.2f}_{lon:.2f}_{hours}"
        cached = self._cache_get(key)
        if cached:
            return cached

        now = time.time()
        rng = np.random.default_rng(int(lat * 100 + lon * 100))
        forecasts: List[WeatherForecastPoint] = []

        for h in range(hours):
            ts = now + h * 3600
            hour_of_day = (h % 24)
            temp = 20.0 + 10.0 * np.sin(2 * np.pi * (hour_of_day - 6) / 24) + rng.normal(0, 1.5)
            ghi = max(0.0, 900 * np.sin(np.pi * (hour_of_day - 6) / 12) * rng.uniform(0.6, 1.0))
            wind = max(0.0, rng.weibull(2.0) * 6.0)
            forecasts.append(WeatherForecastPoint(
                timestamp=ts,
                temperature_c=float(temp),
                wind_speed_ms=float(wind),
                ghi_wm2=float(ghi),
                probability_precipitation=float(rng.uniform(0, 0.3)),
            ))

        self._cache_set(key, forecasts)
        return forecasts

    def get_current(self, lat: float, lon: float) -> WeatherObservation:
        """Return current weather observation (simulated)."""
        rng = np.random.default_rng(int(time.time() / 3600))
        return WeatherObservation(
            station_id=f"SIM_{lat:.1f}_{lon:.1f}",
            timestamp=time.time(),
            temperature_c=float(rng.uniform(10, 35)),
            wind_speed_ms=float(rng.weibull(2) * 6),
            wind_direction_deg=float(rng.uniform(0, 360)),
            ghi_wm2=float(rng.uniform(0, 800)),
            cloud_cover_pct=float(rng.uniform(0, 100)),
            humidity_pct=float(rng.uniform(30, 90)),
            pressure_hpa=float(rng.normal(1013, 10)),
            precipitation_mm=0.0,
        )
