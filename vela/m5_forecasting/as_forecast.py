"""Ancillary Services (AS) price forecasting for ERCOT and CAISO markets."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import NamedTuple


class ASForecast(NamedTuple):
    timestamps: list[datetime]
    reg_up_mean: list[float]      # $/MWh
    reg_down_mean: list[float]    # $/MWh
    spin_mean: list[float]        # $/MWh
    nonspin_mean: list[float]     # $/MWh
    reg_up_p90: list[float]
    reg_down_p90: list[float]
    spin_p90: list[float]
    model: str


ERCOT_AS_SEASONALITY = {
    # (month, hour_of_day) -> relative multiplier for ECRS/Reg-Up
    # Peak summer afternoons have elevated reg prices
    "summer_peak": (6, 16, 2.5),
    "winter_morning": (1, 7, 1.8),
}

# Historical ERCOT average AS prices by hour-of-day (illustrative, $/MWh)
ERCOT_REG_UP_HOURLY_AVG = np.array([
    8.5, 8.2, 7.9, 7.8, 8.1, 9.2,   # 00-05
    11.5, 14.2, 13.8, 12.5, 11.2, 10.5,  # 06-11
    10.8, 11.2, 12.5, 15.8, 18.2, 17.5,  # 12-17
    16.2, 14.5, 12.8, 11.5, 10.2, 9.1,   # 18-23
])

ERCOT_REG_DOWN_HOURLY_AVG = np.array([
    6.2, 6.0, 5.8, 5.7, 5.9, 6.5,
    7.8, 9.5, 9.2, 8.5, 7.8, 7.5,
    7.8, 8.1, 9.0, 11.2, 13.5, 13.0,
    12.2, 10.8, 9.5, 8.5, 7.5, 6.8,
])

ERCOT_SPIN_HOURLY_AVG = np.array([
    4.5, 4.3, 4.1, 4.0, 4.2, 4.8,
    6.2, 7.8, 7.5, 6.8, 6.2, 5.9,
    6.1, 6.4, 7.2, 9.2, 11.0, 10.5,
    9.8, 8.5, 7.5, 6.5, 5.8, 5.1,
])


@dataclass
class ERCOTASForecastModel:
    """
    ERCOT ancillary services price forecast model.

    Uses historical hour-of-day profiles with:
    - Day-of-week adjustment
    - LMP correlation (high LMP → high AS prices)
    - Seasonal multipliers
    - Monte Carlo uncertainty
    """
    noise_frac: float = 0.25  # uncertainty as fraction of mean
    seasonal_factors: dict[int, float] = field(default_factory=lambda: {
        1: 1.2, 2: 1.1, 3: 1.0, 4: 0.95, 5: 1.0,
        6: 1.3, 7: 1.5, 8: 1.4, 9: 1.2, 10: 1.0, 11: 1.0, 12: 1.2,
    })
    _reg_up_profile: np.ndarray = field(init=False, repr=False)
    _reg_down_profile: np.ndarray = field(init=False, repr=False)
    _spin_profile: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._reg_up_profile = ERCOT_REG_UP_HOURLY_AVG.copy()
        self._reg_down_profile = ERCOT_REG_DOWN_HOURLY_AVG.copy()
        self._spin_profile = ERCOT_SPIN_HOURLY_AVG.copy()

    def update_profiles(
        self,
        historical_reg_up: dict[int, list[float]],
        historical_reg_down: dict[int, list[float]],
        historical_spin: dict[int, list[float]],
    ) -> None:
        """Update hourly profiles from historical data (hour -> list of observations)."""
        for h in range(24):
            if h in historical_reg_up and historical_reg_up[h]:
                self._reg_up_profile[h] = np.mean(historical_reg_up[h])
            if h in historical_reg_down and historical_reg_down[h]:
                self._reg_down_profile[h] = np.mean(historical_reg_down[h])
            if h in historical_spin and historical_spin[h]:
                self._spin_profile[h] = np.mean(historical_spin[h])

    def predict(
        self,
        start_time: datetime,
        horizon: int = 24,
        lmp_forecast: list[float] | None = None,
        n_scenarios: int = 200,
        seed: int = 42,
    ) -> ASForecast:
        """
        Forecast AS prices for the given horizon.

        Parameters
        ----------
        start_time : datetime
            UTC start of forecast window
        horizon : int
            Number of hourly intervals
        lmp_forecast : list[float], optional
            LMP energy price forecast — used to scale AS prices
            (high LMP correlates with higher AS prices)
        n_scenarios : int
            Number of Monte Carlo samples for uncertainty
        """
        rng = np.random.default_rng(seed)
        timestamps = [start_time + timedelta(hours=i) for i in range(horizon)]

        reg_up_means, reg_down_means, spin_means, nonspin_means = [], [], [], []
        reg_up_p90s, reg_down_p90s, spin_p90s = [], [], []

        lmp_baseline = 35.0  # $/MWh baseline LMP
        if lmp_forecast is None:
            lmp_forecast = [lmp_baseline] * horizon

        for i, ts in enumerate(timestamps):
            h = ts.hour
            month = ts.month
            dow = ts.weekday()
            seasonal = self.seasonal_factors.get(month, 1.0)
            dow_factor = 0.85 if dow >= 5 else 1.0
            # LMP correlation factor: AS prices scale modestly with LMP
            lmp_factor = 0.8 + 0.2 * min(2.0, lmp_forecast[i] / lmp_baseline)

            ru_base = self._reg_up_profile[h] * seasonal * dow_factor * lmp_factor
            rd_base = self._reg_down_profile[h] * seasonal * dow_factor
            sp_base = self._spin_profile[h] * seasonal * dow_factor * lmp_factor
            ns_base = sp_base * 0.6  # Non-spin typically lower than spin

            # Monte Carlo for uncertainty
            noise_sigma_ru = ru_base * self.noise_frac
            noise_sigma_rd = rd_base * self.noise_frac
            noise_sigma_sp = sp_base * self.noise_frac

            samples_ru = np.maximum(0, rng.normal(ru_base, noise_sigma_ru, n_scenarios))
            samples_rd = np.maximum(0, rng.normal(rd_base, noise_sigma_rd, n_scenarios))
            samples_sp = np.maximum(0, rng.normal(sp_base, noise_sigma_sp, n_scenarios))

            reg_up_means.append(float(np.mean(samples_ru)))
            reg_down_means.append(float(np.mean(samples_rd)))
            spin_means.append(float(np.mean(samples_sp)))
            nonspin_means.append(float(ns_base))
            reg_up_p90s.append(float(np.percentile(samples_ru, 90)))
            reg_down_p90s.append(float(np.percentile(samples_rd, 90)))
            spin_p90s.append(float(np.percentile(samples_sp, 90)))

        return ASForecast(
            timestamps=timestamps,
            reg_up_mean=reg_up_means,
            reg_down_mean=reg_down_means,
            spin_mean=spin_means,
            nonspin_mean=nonspin_means,
            reg_up_p90=reg_up_p90s,
            reg_down_p90=reg_down_p90s,
            spin_p90=spin_p90s,
            model="ERCOT-AS-Profile",
        )


@dataclass
class CAISOASForecastModel:
    """
    CAISO ancillary services forecast model.

    CAISO AS products: Regulation Up, Regulation Down, Spinning Reserve,
    Non-Spinning Reserve.  Uses similar profile-based approach with
    CAISO-specific seasonal patterns.
    """
    noise_frac: float = 0.20

    def predict(
        self,
        start_time: datetime,
        horizon: int = 24,
        lmp_forecast: list[float] | None = None,
    ) -> ASForecast:
        # CAISO reg prices tend to be lower than ERCOT but more stable
        CAISO_REG_UP = np.array([
            6.0, 5.8, 5.5, 5.4, 5.6, 6.2,
            8.5, 10.2, 9.8, 9.0, 8.5, 8.2,
            8.5, 9.0, 10.5, 13.2, 15.5, 14.8,
            13.5, 11.8, 10.2, 8.8, 7.8, 6.8,
        ])
        rng = np.random.default_rng(0)
        timestamps = [start_time + timedelta(hours=i) for i in range(horizon)]
        lmp_baseline = 40.0
        if lmp_forecast is None:
            lmp_forecast = [lmp_baseline] * horizon

        reg_up_means, reg_down_means, spin_means, nonspin_means = [], [], [], []
        reg_up_p90s, reg_down_p90s, spin_p90s = [], [], []

        for i, ts in enumerate(timestamps):
            h = ts.hour
            lmp_f = 0.8 + 0.2 * min(2.0, lmp_forecast[i] / lmp_baseline)
            ru = CAISO_REG_UP[h] * lmp_f
            rd = ru * 0.85
            sp = ru * 0.55
            ns = sp * 0.7
            sigma = ru * self.noise_frac
            samples = np.maximum(0, rng.normal(ru, sigma, 200))
            reg_up_means.append(float(np.mean(samples)))
            reg_down_means.append(float(rd))
            spin_means.append(float(sp))
            nonspin_means.append(float(ns))
            reg_up_p90s.append(float(np.percentile(samples, 90)))
            reg_down_p90s.append(float(rd * 1.3))
            spin_p90s.append(float(sp * 1.3))

        return ASForecast(
            timestamps=timestamps,
            reg_up_mean=reg_up_means,
            reg_down_mean=reg_down_means,
            spin_mean=spin_means,
            nonspin_mean=nonspin_means,
            reg_up_p90=reg_up_p90s,
            reg_down_p90=reg_down_p90s,
            spin_p90=spin_p90s,
            model="CAISO-AS-Profile",
        )
