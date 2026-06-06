"""Performance profiling: profile the optimizer and forecasting pipeline."""
from __future__ import annotations

import cProfile
import io
import logging
import pstats
import time

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def profile_optimizer(horizon: int = 24, n_assets: int = 3) -> None:
    from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer
    import numpy as np

    np.random.seed(42)
    assets = [Asset(asset_id=f"bat-{i:03d}", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5) for i in range(n_assets)]
    daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48, 50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
    lmp = [max(0, daily[h % 24] + np.random.normal(0, 5)) for h in range(horizon)]

    optimizer = MILPDispatchOptimizer(horizon=horizon)
    profiler = cProfile.Profile()
    profiler.enable()
    t0 = time.perf_counter()
    for _ in range(5):
        optimizer.solve(assets=assets, lmp=lmp)
    elapsed = time.perf_counter() - t0
    profiler.disable()

    print(f"\nOptimizer Profile: horizon={horizon}h, assets={n_assets}, 5 runs in {elapsed:.3f}s ({elapsed/5*1000:.1f}ms/run)")
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative")
    stats.print_stats(20)
    print(stream.getvalue())


def profile_forecast(lags: int = 24, horizon: int = 24) -> None:
    from vela.m5_forecasting.price_forecast import ARPriceModel
    import numpy as np

    np.random.seed(7)
    prices = [max(0, 55 + np.random.normal(0, 20)) for _ in range(168)]
    model = ARPriceModel(lags=lags)
    model.fit(prices)

    profiler = cProfile.Profile()
    profiler.enable()
    t0 = time.perf_counter()
    for _ in range(100):
        model.predict(recent=prices[-lags:], horizon=horizon)
    elapsed = time.perf_counter() - t0
    profiler.disable()

    print(f"\nForecast Profile: lags={lags}, horizon={horizon}, 100 inferences in {elapsed:.3f}s ({elapsed/100*1000:.2f}ms/call)")


if __name__ == "__main__":
    profile_optimizer(horizon=24, n_assets=3)
    profile_forecast(lags=24, horizon=24)
