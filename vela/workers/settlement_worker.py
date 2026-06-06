"""Celery task: calculate settlements for all assets after each trading interval."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from vela.workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    name="vela.workers.settlement_worker.calculate_settlement",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def calculate_settlement(
    self,
    asset_ids: list[str] | None = None,
    market: str = "CAISO",
    settlement_date: str | None = None,
) -> dict[str, Any]:
    """
    Run settlement reconciliation for all assets.
    Compares metered output against scheduled dispatch and calculates
    energy revenue minus imbalance charges.
    """
    logger.info("Starting settlement task market=%s date=%s", market, settlement_date)
    try:
        from vela.m9_settlement.settlement_engine import SettlementEngine
        import numpy as np

        if asset_ids is None:
            asset_ids = ["bat-001", "bat-002"]

        date = (
            datetime.fromisoformat(settlement_date)
            if settlement_date
            else datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        )

        engine = SettlementEngine(market=market)
        np.random.seed(42)

        results = []
        for asset_id in asset_ids:
            # Simulate 24-hour metered vs scheduled data
            scheduled = [max(0, np.random.normal(1.5, 0.3)) for _ in range(24)]
            metered = [max(0, s + np.random.normal(0, 0.05)) for s in scheduled]
            lmp = [max(0, 55 + np.random.normal(0, 20)) for _ in range(24)]

            statement = engine.calculate(
                asset_id=asset_id,
                settlement_date=date,
                scheduled_mwh=scheduled,
                metered_mwh=metered,
                lmp=lmp,
            )
            results.append({
                "asset_id": asset_id,
                "total_revenue_usd": round(statement.total_revenue, 2),
                "total_imbalance_usd": round(statement.total_imbalance_charge, 2),
                "net_revenue_usd": round(statement.total_revenue - statement.total_imbalance_charge, 2),
                "total_energy_mwh": round(statement.total_energy_mwh, 3),
            })

        logger.info("Settlement complete for %d assets", len(results))
        return {
            "market": market,
            "settlement_date": date.isoformat(),
            "assets_settled": len(results),
            "results": results,
            "total_fleet_revenue_usd": round(sum(r["net_revenue_usd"] for r in results), 2),
        }

    except Exception as exc:
        logger.error("Settlement failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


@app.task(name="vela.workers.settlement_worker.finalize_statements")
def finalize_statements(cutoff_hours: int = 72) -> dict[str, Any]:
    """Mark preliminary statements as final after the settlement lag period."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)
    logger.info("Finalizing statements older than %s", cutoff.isoformat())
    # In production: query DB for preliminary statements older than cutoff and update status
    return {"finalized": 0, "cutoff": cutoff.isoformat()}
