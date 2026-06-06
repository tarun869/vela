"""Notebook 09: ML model evaluation for price forecasting."""
import numpy as np
from vela.m5_forecasting.price_forecast import ARPriceModel

np.random.seed(42)
DAILY = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
         50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]

# Build 60 days of history
history = []
for d in range(60):
    history.extend([max(0, p + np.random.normal(0, 5 + 2 * np.sin(d / 7))) for p in DAILY])

# Rolling walk-forward evaluation
TRAIN_DAYS = 14
TEST_DAYS = 30
lags_options = [6, 12, 24]

print("Walk-Forward Forecast Evaluation")
print("=" * 60)
print(f"{'Model':>12} {'MAE':>8} {'RMSE':>8} {'MAPE%':>8} {'Coverage':>10}")
print("-" * 50)

for lags in lags_options:
    maes, rmses, mapes, coverages = [], [], [], []
    train_size = TRAIN_DAYS * 24
    for step in range(TEST_DAYS):
        start = step * 24
        train = history[start : start + train_size]
        test = history[start + train_size : start + train_size + 24]
        if len(test) < 24 or len(train) < lags + 1:
            continue
        model = ARPriceModel(lags=lags)
        model.fit(train)
        fc = model.predict(recent=train[-48:], horizon=24)
        actual = np.array(test)
        pred = np.array(fc.mean)
        mae = np.mean(np.abs(actual - pred))
        rmse = np.sqrt(np.mean((actual - pred) ** 2))
        mape = 100 * np.mean(np.abs(actual - pred) / np.maximum(actual, 1e-6))
        cov = np.mean((np.array(fc.p10) <= actual) & (actual <= np.array(fc.p90)))
        maes.append(mae)
        rmses.append(rmse)
        mapes.append(mape)
        coverages.append(cov)
    if maes:
        print(f"{'AR('+str(lags)+')':>12} {np.mean(maes):>8.2f} {np.mean(rmses):>8.2f} {np.mean(mapes):>8.1f} {100*np.mean(coverages):>9.1f}%")

# Best model recommendation
print("\nBest practice: AR(24) captures the full daily seasonality.")
print("For production, consider XGBoost with hour-of-day + day-of-week features.")
print("LSTM models may improve on weeks with irregular demand patterns.")
