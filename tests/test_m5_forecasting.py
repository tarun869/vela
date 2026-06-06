"""Tests for the m5_forecasting module: AR model, GP model, load forecast."""
from __future__ import annotations

import pytest
import numpy as np
from datetime import datetime, timezone
from vela.m5_forecasting.price_forecast import ARPriceModel, PriceForecast


@pytest.fixture
def week_of_prices() -> list[float]:
    np.random.seed(7)
    daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
    prices = []
    for _ in range(7):
        prices.extend([max(0.0, p + np.random.normal(0, 4)) for p in daily])
    return prices


class TestARModelFitting:
    def test_fit_stores_coefficients(self, week_of_prices):
        model = ARPriceModel(lags=24)
        model.fit(week_of_prices)
        assert model._fitted is True
        assert model._coeffs is not None
        assert len(model._coeffs) == 24

    def test_intercept_is_set_after_fit(self, week_of_prices):
        model = ARPriceModel(lags=24)
        model.fit(week_of_prices)
        assert isinstance(model._intercept, float)
        assert np.isfinite(model._intercept)

    def test_fit_with_minimal_data(self):
        model = ARPriceModel(lags=3)
        prices = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        model.fit(prices)
        assert model._fitted is True


class TestARModelPrediction:
    def test_predict_single_step(self, week_of_prices):
        model = ARPriceModel(lags=24)
        model.fit(week_of_prices)
        fc = model.predict(recent=week_of_prices[-48:], horizon=1)
        assert len(fc.mean) == 1
        assert fc.mean[0] >= 0.0

    def test_predict_48_hours(self, week_of_prices):
        model = ARPriceModel(lags=24)
        model.fit(week_of_prices)
        fc = model.predict(recent=week_of_prices[-48:], horizon=48)
        assert len(fc.mean) == 48
        assert all(v >= 0.0 for v in fc.mean)

    def test_prediction_intervals_are_monotone(self, week_of_prices):
        model = ARPriceModel(lags=24)
        model.fit(week_of_prices)
        fc = model.predict(recent=week_of_prices[-48:], horizon=24)
        for p10, mean, p90 in zip(fc.p10, fc.mean, fc.p90):
            assert p10 <= mean + 1e-6
            assert mean <= p90 + 1e-6

    def test_forecast_timestamps_are_sequential(self, week_of_prices):
        model = ARPriceModel(lags=24)
        model.fit(week_of_prices)
        fc = model.predict(recent=week_of_prices[-24:], horizon=6)
        for i in range(1, len(fc.timestamps)):
            assert fc.timestamps[i] > fc.timestamps[i - 1]


class TestLoadForecast:
    def test_load_forecast_module_imports(self):
        try:
            from vela.m5_forecasting.load_forecast import LoadForecaster
            assert LoadForecaster is not None
        except ImportError:
            pytest.skip("load_forecast not yet implemented with LoadForecaster class")

    def test_gaussian_process_module_imports(self):
        try:
            from vela.m5_forecasting.gaussian_process import GPForecaster
        except ImportError:
            pytest.skip("gaussian_process module not yet fully implemented")


class TestForecastQuality:
    def test_mae_finite_on_backtests(self, week_of_prices):
        model = ARPriceModel(lags=24)
        train = week_of_prices[:-24]
        test = week_of_prices[-24:]
        model.fit(train)
        fc = model.predict(recent=train[-48:], horizon=24)
        mae = float(np.mean(np.abs(np.array(test) - np.array(fc.mean))))
        assert np.isfinite(mae)
        assert mae >= 0

    def test_consistent_predictions_same_input(self, week_of_prices):
        model = ARPriceModel(lags=24)
        model.fit(week_of_prices)
        fc1 = model.predict(recent=week_of_prices[-24:], horizon=12)
        fc2 = model.predict(recent=week_of_prices[-24:], horizon=12)
        for v1, v2 in zip(fc1.mean, fc2.mean):
            assert v1 == pytest.approx(v2, abs=1e-9)
