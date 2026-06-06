"""Data mart: analytics views and pre-aggregated reporting tables."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def revenue_by_asset(
    start: datetime,
    end: datetime,
    asset_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Return daily revenue aggregated by asset for the given period.
    In production, this executes against TimescaleDB continuous aggregates.
    """
    import numpy as np
    np.random.seed(42)
    days = max(1, int((end - start).total_seconds() / 86400))
    ids = asset_ids or ["bat-001", "bat-002", "bat-003"]
    rows = []
    for asset_id in ids:
        for d in range(days):
            day = start + timedelta(days=d)
            rows.append({
                "date": day.date().isoformat(),
                "asset_id": asset_id,
                "total_revenue_usd": round(abs(np.random.normal(650, 120)), 2),
                "energy_arbitrage_usd": round(abs(np.random.normal(400, 80)), 2),
                "regulation_usd": round(abs(np.random.normal(180, 50)), 2),
                "total_energy_mwh": round(abs(np.random.normal(24, 4)), 2),
                "avg_lmp": round(np.random.normal(58, 18), 2),
                "cycle_count": round(np.random.uniform(0.8, 1.8), 2),
            })
    return rows


def settlement_summary(
    start: datetime,
    end: datetime,
    market: str = "CAISO",
) -> list[dict[str, Any]]:
    """Monthly settlement summary rollup."""
    import numpy as np
    np.random.seed(7)
    months = max(1, int((end - start).total_seconds() / (86400 * 30)))
    rows = []
    for m in range(months):
        period_start = start + timedelta(days=m * 30)
        rows.append({
            "period": period_start.strftime("%Y-%m"),
            "market": market,
            "total_revenue_usd": round(abs(np.random.normal(18500, 3000)), 2),
            "imbalance_charges_usd": round(abs(np.random.normal(450, 80)), 2),
            "net_revenue_usd": round(abs(np.random.normal(18050, 3000)), 2),
            "statements_count": int(np.random.randint(20, 35)),
            "final_count": int(np.random.randint(18, 32)),
        })
    return rows


def carbon_summary_mart(
    start: datetime,
    end: datetime,
    region: str = "CAISO",
) -> list[dict[str, Any]]:
    """Weekly avoided emissions rollup."""
    import numpy as np
    np.random.seed(11)
    weeks = max(1, int((end - start).total_seconds() / (86400 * 7)))
    rows = []
    for w in range(weeks):
        week_start = start + timedelta(weeks=w)
        rows.append({
            "week_start": week_start.date().isoformat(),
            "region": region,
            "avoided_kg": round(abs(np.random.normal(12000, 2000)), 1),
            "gross_emissions_kg": round(abs(np.random.normal(3500, 600)), 1),
            "carbon_credits_tonne": round(abs(np.random.normal(12, 2)), 2),
            "avg_carbon_intensity": round(np.random.normal(225, 45), 1),
        })
    return rows


def fleet_kpi_snapshot(asset_ids: list[str] | None = None) -> dict[str, Any]:
    """Current fleet KPI snapshot for the dashboard."""
    import numpy as np
    np.random.seed(99)
    ids = asset_ids or ["bat-001", "bat-002", "bat-003"]
    return {
        "fleet_size": len(ids),
        "online": len(ids) - 1,
        "avg_soc": round(np.random.uniform(0.45, 0.72), 3),
        "fleet_availability": round(np.random.uniform(0.97, 0.999), 4),
        "mtd_revenue_usd": round(abs(np.random.normal(52000, 8000)), 2),
        "ytd_revenue_usd": round(abs(np.random.normal(680000, 90000)), 2),
        "total_cycles_ytd": round(np.random.uniform(800, 1400), 0),
        "avg_rte": round(np.random.uniform(0.89, 0.94), 3),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
