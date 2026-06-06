"""Diagnostics CLI: run sanity checks on the Vela stack."""
from __future__ import annotations

import importlib
import sys
import time


REQUIRED_PACKAGES = [
    "numpy", "fastapi", "pydantic", "uvicorn",
    "celery", "redis", "jwt", "sqlalchemy",
]

OPTIONAL_PACKAGES = [
    "strawberry", "prometheus_client", "opentelemetry",
    "httpx", "boto3", "pandas", "pyarrow", "kafka",
]


def cmd_check_imports() -> None:
    """Verify all required Python packages are importable."""
    print("Checking required packages:")
    all_ok = True
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg.replace("-", "_"))
            print(f"  [OK] {pkg}")
        except ImportError:
            print(f"  [MISSING] {pkg}")
            all_ok = False

    print("\nOptional packages:")
    for pkg in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(pkg.replace("-", "_"))
            print(f"  [OK] {pkg}")
        except ImportError:
            print(f"  [not installed] {pkg}")

    if all_ok:
        print("\nAll required packages available.")
    else:
        print("\nSome required packages are missing. Run: pip install -e '.[dev]'")


def cmd_optimizer_smoke_test() -> None:
    """Run a quick optimizer smoke test."""
    print("Running optimizer smoke test...")
    t0 = time.perf_counter()
    try:
        from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer
        asset = Asset(asset_id="diag-bat", capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
        optimizer = MILPDispatchOptimizer(horizon=4)
        lmp = [20.0, 20.0, 100.0, 100.0]
        solution = optimizer.solve(assets=[asset], lmp=lmp)
        elapsed = time.perf_counter() - t0
        print(f"  Status: {solution.status}")
        print(f"  Objective: ${solution.objective:.2f}")
        print(f"  Solve time: {elapsed:.3f}s")
    except Exception as exc:
        print(f"  [ERROR] {exc}")


def cmd_forecast_smoke_test() -> None:
    """Run a quick price forecast smoke test."""
    print("Running forecast smoke test...")
    try:
        from vela.m5_forecasting.price_forecast import ARPriceModel
        import numpy as np
        np.random.seed(42)
        prices = [max(0, 50 + np.random.normal(0, 10)) for _ in range(48)]
        model = ARPriceModel(lags=12)
        model.fit(prices)
        fc = model.predict(recent=prices[-24:], horizon=6)
        print(f"  Forecast (6h): {[round(v, 1) for v in fc.mean]}")
    except Exception as exc:
        print(f"  [ERROR] {exc}")


def cmd_all() -> None:
    """Run all diagnostic checks."""
    cmd_check_imports()
    print()
    cmd_optimizer_smoke_test()
    print()
    cmd_forecast_smoke_test()
