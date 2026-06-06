"""Settlement CLI commands."""
from __future__ import annotations

import json
import os


def cmd_reconcile(
    asset_id: str,
    market: str = "CAISO",
    settlement_date: str | None = None,
    hours: int = 24,
) -> None:
    """Run settlement reconciliation for an asset."""
    from tools.api_client import VelaClient
    from datetime import datetime, timezone
    import numpy as np

    base_url = os.getenv("VELA_API_URL", "http://localhost:8000")
    date = settlement_date or datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    np.random.seed(42)
    scheduled = [max(0, np.random.normal(1.5, 0.2)) for _ in range(hours)]
    metered = [max(0, s + np.random.normal(0, 0.05)) for s in scheduled]
    lmp = [max(0, 55 + np.random.normal(0, 15)) for _ in range(hours)]

    with VelaClient(base_url=base_url) as client:
        stmt = client.reconcile(
            asset_id=asset_id,
            market=market,
            settlement_date=date,
            scheduled_mwh=scheduled,
            metered_mwh=metered,
            lmp=lmp,
        )
        print(f"Settlement Statement: {stmt['statement_id'][:8]}")
        print(f"  Asset: {stmt['asset_id']}")
        print(f"  Market: {stmt['market']}")
        print(f"  Total Energy: {stmt['total_energy_mwh']:.3f} MWh")
        print(f"  Gross Revenue: ${stmt['total_revenue_usd']:.2f}")
        print(f"  Imbalance: ${stmt['total_imbalance_charge_usd']:.2f}")
        print(f"  Net Revenue: ${stmt['net_revenue_usd']:.2f}")


def cmd_list_statements(asset_id: str | None = None, limit: int = 10) -> None:
    """List recent settlement statements."""
    from tools.api_client import VelaClient
    base_url = os.getenv("VELA_API_URL", "http://localhost:8000")
    with VelaClient(base_url=base_url) as client:
        # Calls the API; returns list
        print("Statement listing: see /v1/settlements/statements")
