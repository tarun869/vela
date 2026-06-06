"""
Solar irradiance models for VPP solar generation forecasting.

Implements:
  - Clear-sky GHI model (Ineichen-Perez)
  - Direct Normal Irradiance (DNI) and Diffuse Horizontal Irradiance (DHI)
  - Plane of Array (POA) irradiance for tilted panels
  - Cloud transmittance correction
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class SolarPosition:
    zenith_deg: float        # Solar zenith angle (degrees)
    elevation_deg: float     # Solar elevation angle (degrees)
    azimuth_deg: float       # Solar azimuth angle (degrees, 0=N, 90=E)
    hour_angle_deg: float    # Hour angle (degrees)


def solar_position(
    latitude: float,
    longitude: float,
    datetime_utc: datetime,
) -> SolarPosition:
    """
    Compute solar position using Spencer-Iqbal equations.

    Args:
        latitude: Decimal degrees (positive north)
        longitude: Decimal degrees (positive east)
        datetime_utc: UTC datetime

    Returns:
        SolarPosition object.
    """
    day_of_year = datetime_utc.timetuple().tm_yday
    hour_utc = datetime_utc.hour + datetime_utc.minute / 60.0

    # Equation of time (minutes)
    B = 2 * math.pi * (day_of_year - 1) / 365.0
    eot = 229.18 * (0.000075 + 0.001868 * math.cos(B) - 0.032077 * math.sin(B)
                    - 0.014615 * math.cos(2*B) - 0.04089 * math.sin(2*B))

    # Local solar time
    lstm = 15.0 * round(longitude / 15.0)   # Standard meridian
    tc = 4 * (longitude - lstm) + eot       # Time correction (minutes)
    solar_time = hour_utc + tc / 60.0

    # Hour angle
    hour_angle = 15.0 * (solar_time - 12.0)

    # Declination angle (degrees)
    declination = 23.45 * math.sin(math.radians(360.0 * (284 + day_of_year) / 365.0))

    lat_r = math.radians(latitude)
    dec_r = math.radians(declination)
    ha_r = math.radians(hour_angle)

    cos_z = (math.sin(lat_r) * math.sin(dec_r) +
             math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r))
    cos_z = max(-1.0, min(1.0, cos_z))
    zenith_deg = math.degrees(math.acos(cos_z))
    elevation_deg = 90.0 - zenith_deg

    # Azimuth
    if elevation_deg > 0:
        sin_az = (-math.cos(dec_r) * math.sin(ha_r)) / math.cos(math.radians(elevation_deg))
        sin_az = max(-1.0, min(1.0, sin_az))
        azimuth_deg = math.degrees(math.asin(sin_az))
        if hour_angle > 0:
            azimuth_deg = 180.0 - azimuth_deg
        else:
            azimuth_deg += 180.0
    else:
        azimuth_deg = 0.0

    return SolarPosition(
        zenith_deg=zenith_deg,
        elevation_deg=elevation_deg,
        azimuth_deg=azimuth_deg,
        hour_angle_deg=hour_angle,
    )


class ClearSkyModel:
    """
    Clear-sky irradiance model (simplified Ineichen-Perez).

    Computes GHI, DNI, DHI for clear-sky conditions.
    """

    SOLAR_CONSTANT = 1361.0  # W/m^2 (TSI)

    def __init__(
        self,
        latitude: float,
        longitude: float,
        altitude_m: float = 0.0,
        linke_turbidity: float = 3.0,
    ) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.altitude_m = altitude_m
        self.linke_turbidity = linke_turbidity  # Typical: 2 (clear) to 6 (hazy)

    def _extraterrestrial_irradiance(self, day_of_year: int) -> float:
        """Extraterrestrial radiation (W/m^2) accounting for Earth-Sun distance."""
        B = 2 * math.pi * (day_of_year - 1) / 365.0
        correction = 1.000110 + 0.034221 * math.cos(B) + 0.001280 * math.sin(B)
        return self.SOLAR_CONSTANT * correction

    def ghi(self, datetime_utc: datetime) -> Tuple[float, float, float]:
        """
        Compute GHI, DNI, DHI at a specific datetime.

        Returns:
            (GHI, DNI, DHI) in W/m^2. All zero if sun is below horizon.
        """
        pos = solar_position(self.latitude, self.longitude, datetime_utc)
        if pos.elevation_deg <= 0:
            return 0.0, 0.0, 0.0

        day = datetime_utc.timetuple().tm_yday
        et_rad = self._extraterrestrial_irradiance(day)

        cos_z = math.cos(math.radians(pos.zenith_deg))

        # Ineichen-Perez clear-sky model (simplified)
        am = 1.0 / (cos_z + 0.50572 * (96.07995 - pos.zenith_deg) ** (-1.6364))  # Air mass
        fh1 = math.exp(-self.altitude_m / 8000.0)
        fh2 = math.exp(-self.altitude_m / 1250.0)

        cg1 = 5.09e-5 * self.altitude_m + 0.868
        cg2 = 3.92e-5 * self.altitude_m + 0.0387

        Ib = cg1 * et_rad * math.exp(-cg2 * am * (fh1 + fh2 * (self.linke_turbidity - 1)))
        Ib = max(0.0, Ib)

        # Diffuse component
        b = 0.664 + 0.163 / fh1
        Fd = b * et_rad * (1 - Ib / (et_rad + 1e-6)) * cos_z * fh1
        Id = max(0.0, Fd)

        ghi_val = max(0.0, Ib * cos_z + Id)
        return ghi_val, Ib, Id

    def ghi_series(
        self,
        n_hours: int,
        start_hour: int = 0,
        start_day: int = 180,
    ) -> np.ndarray:
        """Generate hourly GHI series."""
        from datetime import datetime, timezone
        base_date = datetime(2024, 6, 28, start_hour, 0, tzinfo=timezone.utc)  # Summer day
        series = []
        for h in range(n_hours):
            from datetime import timedelta
            dt = base_date + timedelta(hours=h + start_day * 24 // 24)
            ghi_val, _, _ = self.ghi(dt)
            series.append(ghi_val)
        return np.array(series)

    def poa_irradiance(
        self,
        datetime_utc: datetime,
        tilt_deg: float,
        azimuth_deg: float = 180.0,  # South-facing
        albedo: float = 0.2,
    ) -> float:
        """
        Plane of Array (POA) irradiance for a tilted surface.

        Args:
            tilt_deg: Panel tilt angle from horizontal.
            azimuth_deg: Panel azimuth (180=south-facing).
            albedo: Ground reflectance.

        Returns:
            POA irradiance (W/m^2).
        """
        ghi_val, dni, dhi = self.ghi(datetime_utc)
        pos = solar_position(self.latitude, self.longitude, datetime_utc)

        if pos.elevation_deg <= 0:
            return 0.0

        tilt_r = math.radians(tilt_deg)
        surface_az_r = math.radians(azimuth_deg)
        solar_az_r = math.radians(pos.azimuth_deg)
        zenith_r = math.radians(pos.zenith_deg)

        # Angle of incidence
        cos_aoi = (
            math.sin(zenith_r) * math.sin(tilt_r) * math.cos(solar_az_r - surface_az_r)
            + math.cos(zenith_r) * math.cos(tilt_r)
        )
        cos_aoi = max(0.0, cos_aoi)

        # Perez diffuse model (simplified isotropic)
        poa_direct = dni * cos_aoi
        poa_diffuse = dhi * (1 + math.cos(tilt_r)) / 2.0
        poa_ground = ghi_val * albedo * (1 - math.cos(tilt_r)) / 2.0

        return max(0.0, poa_direct + poa_diffuse + poa_ground)
