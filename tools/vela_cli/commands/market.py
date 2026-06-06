"""Market CLI commands."""
from __future__ import annotations

import json
import os


def cmd_prices(node: str = "TH_NP15_GEN-APND", hours: int = 24) -> None:
    """Fetch and print recent LMP prices."""
    from tools.api_client import VelaClient
    base_url = os.getenv("VELA_API_URL", "http://localhost:8000")
    with VelaClient(base_url=base_url) as client:
        prices = client.get_market_prices(node=node, hours=hours)
        print(f"{'Timestamp':<25} {'LMP':>10}")
        print("-" * 40)
        for p in prices:
            print(f"{str(p['interval_start'])[:19]:<25} {p['lmp']:>10.2f}")


def cmd_forecast(node: str = "TH_NP15_GEN-APND", horizon: int = 24) -> None:
    """Print LMP price forecast."""
    from tools.api_client import VelaClient
    base_url = os.getenv("VELA_API_URL", "http://localhost:8000")
    with VelaClient(base_url=base_url) as client:
        fc = client.forecast_price(node=node, horizon_hours=horizon)
        print(f"Forecast for {node} | model={fc['model']}")
        print(f"{'Hour':>5} {'Mean':>8} {'P10':>8} {'P90':>8}")
        print("-" * 35)
        for i, p in enumerate(fc["points"]):
            print(f"{i+1:>5} {p['mean']:>8.2f} {p['p10']:>8.2f} {p['p90']:>8.2f}")
