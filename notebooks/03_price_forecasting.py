"""Notebook 03: Price forecasting model development and evaluation."""
import numpy as np
from vela.m5_forecasting.price_forecast import ARPriceModel

np.random.seed(42)
DAILY = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
         50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
# Generate 14 days of synthetic history
history = []
for _ in range(14):
    history.extend([max(0, p + np.random.normal(0, 5)) for p in DAILY])

# Split train / test (last 24h = test)
train = history[:-24]
test = history[-24:]

# Fit AR(24) model
model = ARPriceModel(lags=24)
model.fit(train)

# Forecast
fc = model.predict(recent=train[-48:], horizon=24)

# Evaluate
mae = float(np.mean(np.abs(np.array(test) - np.array(fc.mean))))
rmse = float(np.sqrt(np.mean((np.array(test) - np.array(fc.mean))**2)))
corr = float(np.corrcoef(test, fc.mean)[0, 1])

print("Price Forecast Evaluation (AR-24 model)")
print("=" * 50)
print(f"MAE:  ${mae:.2f}/MWh")
print(f"RMSE: ${rmse:.2f}/MWh")
print(f"Corr: {corr:.3f}")
print()
print(f"{'Hour':>4} {'Actual':>8} {'Forecast':>10} {'P10':>8} {'P90':>8} {'Error':>8}")
print("-" * 50)
for h in range(24):
    err = test[h] - fc.mean[h]
    print(f"{h+1:>4} {test[h]:>8.2f} {fc.mean[h]:>10.2f} {fc.p10[h]:>8.2f} {fc.p90[h]:>8.2f} {err:>8.2f}")

# Coverage: what % of actuals fall within P10-P90
in_interval = sum(1 for h in range(24) if fc.p10[h] <= test[h] <= fc.p90[h])
print(f"\nInterval Coverage (P10-P90): {in_interval}/24 = {100*in_interval/24:.1f}%")
