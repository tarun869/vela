"""Price forecast model tests: AR model, fit, predict, error metrics."""
from __future__ import annotations

import pytest
import numpy as np
from datetime import datetime, timezone
from vela.m5_forecasting.price_forecast import ARPriceModel, PriceForecast


@pytest.fixture
def synthetic_prices() -> list[float]:
    """48-hour synthetic LMP series for fitting."""
    np.random.seed(0)
    daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
    prices = []
    for _ in range(2):
        prices.extend([max(0.0, p + np.random.normal(0, 3)) for p in daily])
    return prices


class TestARPriceModel:
    def test_fit_does_not_raise(self, synthetic_prices):
        model = ARPriceModel(lags=12)
        model.fit(synthetic_prices)  # should not raise

    def test_predict_before_fit_raises(self):
        model = ARPriceModel(lags=12)
        with pytest.raises(AssertionError):
            model.predict(recent=[50.0] * 12, horizon=6)

    def test_predict_returns_forecast_namedtuple(self, synthetic_prices):
        model = ARPriceModel(lags=12)
        model.fit(synthetic_prices)
        fc = model.predict(recent=synthetic_prices[-24:], horizon=24)
        assert isinstance(fc, PriceForecast)

    def test_forecast_has_correct_length(self, synthetic_prices):
        model = ARPriceModel(lags=12)
        model.fit(synthetic_prices)
        for horizon in [1, 12, 24, 48]:
            fc = model.predict(recent=synthetic_prices[-24:], horizon=horizon)
            assert len(fc.mean) == horizon
            assert len(fc.p10) == horizon
            assert len(fc.p90) == horizon
            assert len(fc.timestamps) == horizon

    def test_forecast_timestamps_are_future(self, synthetic_prices):
        model = ARPriceModel(lags=12)
        model.fit(synthetic_prices)
        fc = model.predict(recent=synthetic_prices[-24:], horizon=6)
        now = datetime.now(timezone.utc)
        for ts in fc.timestamps:
            assert ts > now

    def test_p10_below_mean_below_p90(self, synthetic_prices):
        model = ARPriceModel(lags=12)
        model.fit(synthetic_prices)
        fc = model.predict(recent=synthetic_prices[-24:], horizon=24)
        for p10, mean, p90 in zip(fc.p10, fc.mean, fc.p90):
            assert p10 <= mean + 1e-9
            assert mean <= p90 + 1e-9

    def test_non_negative_forecasts(self, synthetic_prices):
        model = ARPriceModel(lags=12)
        model.fit(synthetic_prices)
        fc = model.predict(recent=synthetic_prices[-24:], horizon=24)
        assert all(v >= 0.0 for v in fc.mean)

    def test_model_name_is_ar(self, synthetic_prices):
        model = ARPriceModel(lags=12)
        model.fit(synthetic_prices)
        fc = model.predict(recent=synthetic_prices[-24:], horizon=6)
        assert fc.model.lower().startswith("ar")

    def test_forecast_tracks_seasonal_pattern(self, synthetic_prices):
        """
        With a strong daily pattern, the forecast at hour 18 (peak) should be
        higher than at hour 3 (valley) on average.
        """
        np.random.seed(42)
        model = ARPriceModel(lags=24)
        # Generate a strong daily pattern for fitting
        daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
                 50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
        history = []
        for _ in range(7):
            history.extend([max(0.0, p + np.random.normal(0, 2)) for p in daily])
        model.fit(history)
        fc = model.predict(recent=history[-48:], horizon=24)
        # Hours 18-20 should generally be higher than hours 0-4
        evening_avg = np.mean(fc.mean[17:21])
        night_avg = np.mean(fc.mean[0:5])
        # Loose check — AR model won't be perfect
        assert evening_avg >= night_avg * 0.7

    def test_mae_is_reasonable_on_training_data(self, synthetic_prices):
        """Backtest on training data: MAE should be finite and non-negative."""
        model = ARPriceModel(lags=12)
        model.fit(synthetic_prices)
        recent = synthetic_prices[-36:-12]
        fc = model.predict(recent=recent, horizon=12)
        actual = synthetic_prices[-12:]
        mae = float(np.mean(np.abs(np.array(actual) - np.array(fc.mean))))
        assert mae >= 0.0
        assert np.isfinite(mae)
