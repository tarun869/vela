"""Load/demand forecasting with weather and calendar features."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import NamedTuple


class LoadForecast(NamedTuple):
    timestamps: list[datetime]
    mean_mw: list[float]
    p10_mw: list[float]
    p90_mw: list[float]
    model: str


@dataclass
class WeatherFeatures:
    """Weather inputs for load forecasting."""
    temperature_f: float
    humidity_pct: float
    wind_mph: float = 0.0
    cloud_cover_pct: float = 0.0

    @property
    def heat_index(self) -> float:
        """Apparent temperature accounting for humidity."""
        if self.temperature_f >= 80:
            hi = (
                -42.379
                + 2.04901523 * self.temperature_f
                + 10.14333127 * self.humidity_pct
                - 0.22475541 * self.temperature_f * self.humidity_pct
                - 6.83783e-3 * self.temperature_f ** 2
                - 5.481717e-2 * self.humidity_pct ** 2
                + 1.22874e-3 * self.temperature_f ** 2 * self.humidity_pct
                + 8.5282e-4 * self.temperature_f * self.humidity_pct ** 2
                - 1.99e-6 * self.temperature_f ** 2 * self.humidity_pct ** 2
            )
            return hi
        return self.temperature_f

    @property
    def cooling_degree_hours(self) -> float:
        """CDH above 65F baseline."""
        return max(0.0, self.heat_index - 65.0)

    @property
    def heating_degree_hours(self) -> float:
        """HDH below 65F baseline."""
        return max(0.0, 65.0 - self.temperature_f)


def _hour_of_week_features(dt: datetime) -> np.ndarray:
    """One-hot encode hour-of-week (168 features)."""
    dow = dt.weekday()  # 0=Monday
    hour = dt.hour
    idx = dow * 24 + hour
    vec = np.zeros(168)
    vec[idx] = 1.0
    return vec


@dataclass
class LoadForecastModel:
    """
    Gradient-boosting-style load forecaster using linear regression
    on engineered features: hour-of-week, temperature, humidity, lag.

    In production this would be replaced by a trained XGBoost/LightGBM model,
    but the feature engineering pipeline and inference interface are identical.
    """
    n_lags: int = 48  # 48-hour lookback
    _weights: np.ndarray = field(default=None, init=False, repr=False)
    _bias: float = field(default=0.0, init=False, repr=False)
    _fitted: bool = field(default=False, init=False, repr=False)
    _mean_load: float = field(default=100.0, init=False, repr=False)
    _std_load: float = field(default=20.0, init=False, repr=False)

    def _build_features(
        self,
        dt: datetime,
        weather: WeatherFeatures,
        lag_loads: list[float],
    ) -> np.ndarray:
        """Build feature vector for a single interval."""
        # Lag features (last 48 hours)
        lag_arr = np.array(lag_loads[-self.n_lags:], dtype=float)
        if len(lag_arr) < self.n_lags:
            lag_arr = np.pad(lag_arr, (self.n_lags - len(lag_arr), 0), constant_values=self._mean_load)
        lag_norm = (lag_arr - self._mean_load) / (self._std_load + 1e-6)

        # Weather features
        wx = np.array([
            weather.cooling_degree_hours / 30.0,
            weather.heating_degree_hours / 30.0,
            weather.humidity_pct / 100.0,
            weather.wind_mph / 30.0,
        ])

        # Calendar: sin/cos encoding of hour and day-of-week
        h = dt.hour
        d = dt.weekday()
        cal = np.array([
            np.sin(2 * np.pi * h / 24),
            np.cos(2 * np.pi * h / 24),
            np.sin(2 * np.pi * d / 7),
            np.cos(2 * np.pi * d / 7),
            float(d >= 5),  # weekend flag
        ])

        return np.concatenate([lag_norm, wx, cal])

    def fit(
        self,
        historical_loads: list[float],
        historical_weather: list[WeatherFeatures],
        historical_timestamps: list[datetime],
    ) -> None:
        """Fit model via ordinary least squares."""
        assert len(historical_loads) == len(historical_weather) == len(historical_timestamps)
        self._mean_load = float(np.mean(historical_loads))
        self._std_load = float(np.std(historical_loads))

        X_rows = []
        y_rows = []
        for i in range(self.n_lags, len(historical_loads)):
            feat = self._build_features(
                historical_timestamps[i],
                historical_weather[i],
                historical_loads[:i],
            )
            X_rows.append(feat)
            y_rows.append(historical_loads[i])

        X = np.array(X_rows)
        y = np.array(y_rows)
        X_bias = np.hstack([np.ones((len(X), 1)), X])
        result = np.linalg.lstsq(X_bias, y, rcond=None)
        coeffs = result[0]
        self._bias = float(coeffs[0])
        self._weights = coeffs[1:]
        self._fitted = True

    def predict(
        self,
        recent_loads: list[float],
        forecast_weather: list[WeatherFeatures],
        start_time: datetime,
        horizon: int = 24,
    ) -> LoadForecast:
        assert self._fitted, "Model must be fitted before prediction"
        assert len(forecast_weather) >= horizon

        preds = []
        loads_window = list(recent_loads)
        for step in range(horizon):
            dt = start_time + timedelta(hours=step)
            feat = self._build_features(dt, forecast_weather[step], loads_window)
            val = self._bias + float(np.dot(self._weights, feat))
            val = max(0.0, val)
            preds.append(val)
            loads_window.append(val)

        ts = [start_time + timedelta(hours=i) for i in range(horizon)]
        # Uncertainty grows with forecast horizon
        base_sigma = self._std_load * 0.05
        sigmas = [base_sigma * (1 + 0.02 * i) for i in range(horizon)]

        return LoadForecast(
            timestamps=ts,
            mean_mw=preds,
            p10_mw=[max(0, p - 1.28 * s) for p, s in zip(preds, sigmas)],
            p90_mw=[p + 1.28 * s for p, s in zip(preds, sigmas)],
            model="LoadAR-Weather",
        )


def make_synthetic_load_history(
    n_hours: int = 8760,
    base_mw: float = 100.0,
    seed: int = 42,
) -> tuple[list[float], list[WeatherFeatures], list[datetime]]:
    """Generate a year of synthetic load data for testing."""
    rng = np.random.default_rng(seed)
    now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    timestamps = [now + timedelta(hours=i) for i in range(n_hours)]
    loads = []
    weather = []
    for i, dt in enumerate(timestamps):
        # Diurnal pattern
        hour_factor = 1.0 + 0.3 * np.sin(2 * np.pi * (dt.hour - 6) / 24)
        # Day-of-week pattern (weekends lower)
        dow_factor = 0.85 if dt.weekday() >= 5 else 1.0
        # Seasonal temperature (Northern Hemisphere)
        day_of_year = dt.timetuple().tm_yday
        temp_f = 55 + 30 * np.sin(2 * np.pi * (day_of_year - 80) / 365)
        humidity = 50 + 20 * rng.standard_normal()
        wx = WeatherFeatures(
            temperature_f=float(temp_f + 5 * rng.standard_normal()),
            humidity_pct=float(np.clip(humidity, 20, 95)),
            wind_mph=float(abs(10 * rng.standard_normal())),
        )
        cdh = wx.cooling_degree_hours
        hdh = wx.heating_degree_hours
        temp_load = 0.8 * cdh + 0.5 * hdh
        load = base_mw * hour_factor * dow_factor + temp_load + 3 * rng.standard_normal()
        loads.append(float(max(10, load)))
        weather.append(wx)
    return loads, weather, timestamps
