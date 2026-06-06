"""Solar generation forecasting using irradiance data and clear-sky models."""
from __future__ import annotations

import math
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import NamedTuple


class SolarForecast(NamedTuple):
    timestamps: list[datetime]
    ghi_wm2: list[float]        # Global Horizontal Irradiance
    generation_mw: list[float]  # AC output
    p10_mw: list[float]
    p90_mw: list[float]
    model: str


@dataclass
class SolarArrayConfig:
    """Physical parameters of a solar PV array."""
    capacity_mwp: float          # DC nameplate capacity
    tilt_deg: float = 25.0       # Panel tilt angle
    azimuth_deg: float = 180.0   # Panel azimuth (180 = south-facing)
    latitude: float = 37.7       # Site latitude
    longitude: float = -122.4    # Site longitude
    dc_ac_ratio: float = 1.2     # DC/AC inverter loading ratio
    system_losses: float = 0.14  # Soiling, wiring, mismatch losses
    temp_coeff: float = -0.004   # Power temp coefficient (/°C)
    noct: float = 45.0           # Nominal Operating Cell Temperature (°C)


def _declination(day_of_year: int) -> float:
    """Solar declination angle in radians (Spencer 1971)."""
    B = 2 * math.pi * (day_of_year - 1) / 365
    return math.radians(
        0.006918
        - 0.399912 * math.cos(B)
        + 0.070257 * math.sin(B)
        - 0.006758 * math.cos(2 * B)
        + 0.000907 * math.sin(2 * B)
        - 0.002697 * math.cos(3 * B)
        + 0.00148 * math.sin(3 * B)
    )


def _hour_angle(hour_utc: float, longitude_deg: float) -> float:
    """Solar hour angle in radians."""
    solar_time = hour_utc + longitude_deg / 15.0
    return math.radians(15.0 * (solar_time - 12.0))


def clear_sky_ghi(dt: datetime, lat: float, lon: float) -> float:
    """
    Estimate clear-sky GHI (W/m²) using the simplified Bird & Hulstrom model.
    Returns 0 for night-time hours.
    """
    doy = dt.timetuple().tm_yday
    delta = _declination(doy)
    lat_rad = math.radians(lat)
    ha = _hour_angle(dt.hour + dt.minute / 60.0, lon)

    cos_sza = (
        math.sin(lat_rad) * math.sin(delta)
        + math.cos(lat_rad) * math.cos(delta) * math.cos(ha)
    )
    cos_sza = max(0.0, cos_sza)  # No negative values (night)
    if cos_sza < 0.01:
        return 0.0

    # Extraterrestrial radiation
    E0 = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    I_sc = 1361.0  # Solar constant W/m²
    I_0 = I_sc * E0 * cos_sza

    # Simple atmospheric transmittance (Beer-Lambert approximation)
    air_mass = 1.0 / (cos_sza + 0.50572 * (96.07995 - math.degrees(math.acos(cos_sza))) ** -1.6364)
    air_mass = min(air_mass, 38.0)
    tau = 0.7 ** (air_mass ** 0.678)

    return I_0 * tau


def _cell_temperature(ghi: float, ambient_c: float, noct: float) -> float:
    """Estimate PV cell temperature from NOCT model."""
    return ambient_c + ghi * (noct - 20) / 800.0


@dataclass
class SolarForecastModel:
    """
    Solar PV generation forecaster.

    Combines a clear-sky model with a cloud-cover correction factor.
    Cloud cover can be fed from a NWP (Numerical Weather Prediction) source.
    """
    array: SolarArrayConfig

    def ghi_to_power(self, ghi: float, ambient_temp_c: float = 20.0) -> float:
        """Convert GHI (W/m²) to AC generation (MW)."""
        if ghi <= 0:
            return 0.0
        # POA (Plane of Array) irradiance — simplified; full model would use transposition
        poa = ghi * (1 - self.array.system_losses)
        # Cell temperature correction
        t_cell = _cell_temperature(ghi, ambient_temp_c, self.array.noct)
        temp_correction = 1 + self.array.temp_coeff * (t_cell - 25.0)
        dc_power_mw = self.array.capacity_mwp * (poa / 1000.0) * temp_correction
        ac_power_mw = dc_power_mw / self.array.dc_ac_ratio
        return float(max(0.0, ac_power_mw))

    def forecast(
        self,
        start_time: datetime,
        horizon: int = 24,
        cloud_cover_fracs: list[float] | None = None,
        ambient_temps_c: list[float] | None = None,
    ) -> SolarForecast:
        """
        Generate solar generation forecast.

        Parameters
        ----------
        start_time : datetime
            UTC start of forecast window
        horizon : int
            Number of hourly intervals
        cloud_cover_fracs : list[float], optional
            Fraction of sky covered by clouds (0=clear, 1=overcast) per interval.
            Defaults to 0.2 (lightly cloudy).
        ambient_temps_c : list[float], optional
            Ambient temperature in Celsius per interval.
        """
        if cloud_cover_fracs is None:
            cloud_cover_fracs = [0.2] * horizon
        if ambient_temps_c is None:
            ambient_temps_c = [20.0] * horizon

        timestamps = [start_time + timedelta(hours=i) for i in range(horizon)]
        ghi_vals = []
        gen_vals = []

        for dt, cc, t_amb in zip(timestamps, cloud_cover_fracs, ambient_temps_c):
            cs_ghi = clear_sky_ghi(dt, self.array.latitude, self.array.longitude)
            # Cloud correction: Erbs decomposition simplified
            kt = 1.0 - 0.75 * (cc ** 3.4)
            actual_ghi = cs_ghi * kt
            gen = self.ghi_to_power(actual_ghi, t_amb)
            ghi_vals.append(actual_ghi)
            gen_vals.append(gen)

        # Uncertainty: larger for higher cloud cover, grows with horizon
        sigmas = [
            g * (0.05 + 0.03 * cc + 0.005 * i)
            for i, (g, cc) in enumerate(zip(gen_vals, cloud_cover_fracs))
        ]

        return SolarForecast(
            timestamps=timestamps,
            ghi_wm2=ghi_vals,
            generation_mw=gen_vals,
            p10_mw=[max(0, g - 1.28 * s) for g, s in zip(gen_vals, sigmas)],
            p90_mw=[g + 1.28 * s for g, s in zip(gen_vals, sigmas)],
            model="ClearSky-CloudCorrection",
        )

    def actual_vs_forecast(
        self,
        actual_generation: list[float],
        forecast: SolarForecast,
    ) -> dict[str, float]:
        """Calculate forecast skill metrics."""
        actual = np.array(actual_generation)
        pred = np.array(forecast.generation_mw)
        mae = float(np.mean(np.abs(actual - pred)))
        rmse = float(np.sqrt(np.mean((actual - pred) ** 2)))
        capacity = self.array.capacity_mwp / self.array.dc_ac_ratio
        nrmse = rmse / (capacity + 1e-6)
        daytime = actual > 0.01
        if daytime.any():
            mbe = float(np.mean((pred[daytime] - actual[daytime])))
        else:
            mbe = 0.0
        return {"mae_mw": mae, "rmse_mw": rmse, "nrmse": nrmse, "mbe_mw": mbe}
