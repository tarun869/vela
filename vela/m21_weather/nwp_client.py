"""
NWP (Numerical Weather Prediction) client for weather forecast ingestion.

Interfaces with GFS, HRRR, and ERA5 weather model outputs to provide
solar irradiance, wind speed, and temperature forecasts for VPP operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np
from numpy.random import default_rng


@dataclass
class NWPConfig:
    model_name: str          # "GFS", "HRRR", "NAM", "ERA5"
    api_url: Optional[str]   # API endpoint
    api_key: Optional[str]
    resolution_deg: float    # Spatial resolution (degrees)
    update_frequency_h: int  # How often model updates
    forecast_horizon_h: int  # Forecast length (hours)


@dataclass
class WeatherForecast:
    model: str
    init_time: str           # Model initialization time
    valid_times: List[str]   # Valid times for forecast
    latitude: float
    longitude: float
    temperature_c: List[float]
    wind_speed_ms: List[float]
    wind_direction_deg: List[float]
    ghi_wm2: List[float]     # Global horizontal irradiance (W/m^2)
    cloud_cover_pct: List[float]
    precipitation_mm: List[float]
    relative_humidity_pct: List[float]
    pressure_hpa: List[float]


class NWPClient:
    """
    Numerical Weather Prediction client with synthetic data generation
    (production would connect to actual weather APIs).
    """

    MODELS = {
        "GFS": NWPConfig("GFS", None, None, 0.25, 6, 384),
        "HRRR": NWPConfig("HRRR", None, None, 0.03, 1, 48),
        "NAM": NWPConfig("NAM", None, None, 0.12, 6, 60),
    }

    def __init__(self, model_name: str = "HRRR", seed: int = 42) -> None:
        self.config = self.MODELS.get(model_name, self.MODELS["HRRR"])
        self.rng = default_rng(seed)

    def fetch_forecast(
        self,
        latitude: float,
        longitude: float,
        hours: int = 48,
        init_time: Optional[str] = None,
    ) -> WeatherForecast:
        """
        Fetch weather forecast for a location.

        In production: calls NWS API, Open-Meteo, or commercial provider.
        Here: generates physically realistic synthetic forecast.
        """
        now = datetime.now(timezone.utc)
        init_t = init_time or now.isoformat()

        valid_times = [
            (now + timedelta(hours=h)).isoformat()
            for h in range(hours)
        ]

        # Synthetic temperature with diurnal cycle
        hour_of_day = np.array([h % 24 for h in range(hours)])
        t_mean = 20.0 - (latitude - 35) * 0.5  # Rough latitude adjustment
        temperature = t_mean + 8.0 * np.sin(2 * np.pi * (hour_of_day - 6) / 24) + self.rng.normal(0, 1.5, hours)

        # Wind speed (Weibull distribution)
        wind_speed = self.rng.weibull(2.0, hours) * 7.0
        wind_dir = self.rng.uniform(0, 360, hours)

        # Cloud cover (beta distribution, clipped)
        cloud = np.clip(self.rng.beta(2, 3, hours) * 100, 0, 100)

        # GHI with diurnal cycle and cloud attenuation
        from vela.m21_weather.solar_irradiance import ClearSkyModel
        clear_sky = ClearSkyModel(latitude=latitude, longitude=longitude)
        ghi = clear_sky.ghi_series(hours, start_hour=now.hour)
        ghi = ghi * (1 - cloud / 100 * 0.7)  # Cloud attenuation

        return WeatherForecast(
            model=self.config.model_name,
            init_time=init_t,
            valid_times=valid_times,
            latitude=latitude,
            longitude=longitude,
            temperature_c=temperature.tolist(),
            wind_speed_ms=wind_speed.tolist(),
            wind_direction_deg=wind_dir.tolist(),
            ghi_wm2=np.maximum(0, ghi).tolist(),
            cloud_cover_pct=cloud.tolist(),
            precipitation_mm=np.maximum(0, self.rng.exponential(0.2, hours)).tolist(),
            relative_humidity_pct=np.clip(50 + self.rng.normal(0, 15, hours), 10, 100).tolist(),
            pressure_hpa=np.clip(1013 + self.rng.normal(0, 10, hours), 990, 1040).tolist(),
        )

    def ensemble_forecast(
        self,
        latitude: float,
        longitude: float,
        hours: int = 48,
        n_members: int = 10,
    ) -> Dict[str, np.ndarray]:
        """
        Generate ensemble weather forecast for uncertainty quantification.

        Returns dict of variable -> (n_members, n_hours) arrays.
        """
        members = [self.fetch_forecast(latitude, longitude, hours) for _ in range(n_members)]
        return {
            "temperature_c": np.array([m.temperature_c for m in members]),
            "wind_speed_ms": np.array([m.wind_speed_ms for m in members]),
            "ghi_wm2": np.array([m.ghi_wm2 for m in members]),
        }
