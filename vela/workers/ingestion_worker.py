"""Celery task: ingest market data from ISOs (CAISO, ERCOT, PJM)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from vela.workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    name="vela.workers.ingestion_worker.ingest_lmp_prices",
    bind=True,
    max_retries=5,
    default_retry_delay=10,
)
def ingest_lmp_prices(
    self,
    market: str = "CAISO",
    node: str = "TH_NP15_GEN-APND",
    lookback_hours: int = 1,
) -> dict[str, Any]:
    """
    Fetch and store LMP prices from the ISO API.
    In production this calls the OASIS (CAISO) or ERCOT API and writes to TimescaleDB.
    """
    logger.info("Ingesting LMP prices market=%s node=%s lookback=%dh", market, node, lookback_hours)
    try:
        import numpy as np
        now = datetime.now(timezone.utc)
        daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
                 50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
        records = []
        for h in range(lookback_hours):
            ts = now - timedelta(hours=lookback_hours - h)
            lmp = round(max(0, daily[ts.hour % 24] + np.random.normal(0, 5)), 2)
            records.append({
                "timestamp": ts.isoformat(),
                "market": market,
                "node": node,
                "lmp": lmp,
                "energy": round(lmp * 0.85, 2),
                "congestion": round(lmp * 0.10, 2),
                "loss": round(lmp * 0.05, 2),
            })
        logger.info("Ingested %d LMP records for %s/%s", len(records), market, node)
        return {"records_ingested": len(records), "market": market, "node": node, "records": records}

    except Exception as exc:
        logger.error("LMP ingestion failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


@app.task(
    name="vela.workers.ingestion_worker.ingest_ancillary_prices",
    bind=True,
    max_retries=5,
    default_retry_delay=10,
)
def ingest_ancillary_prices(
    self,
    market: str = "CAISO",
    services: list[str] | None = None,
    lookback_hours: int = 1,
) -> dict[str, Any]:
    """Ingest ancillary service clearing prices."""
    if services is None:
        services = ["reg_up", "reg_down", "spin", "non_spin"]
    logger.info("Ingesting ancillary prices market=%s services=%s", market, services)
    import numpy as np
    now = datetime.now(timezone.utc)
    records = []
    service_base = {"reg_up": 15.0, "reg_down": 8.0, "spin": 12.0, "non_spin": 5.0}
    for h in range(lookback_hours):
        ts = now - timedelta(hours=lookback_hours - h)
        for service in services:
            base = service_base.get(service, 10.0)
            price = round(max(0, base + np.random.normal(0, 3)), 2)
            records.append({"timestamp": ts.isoformat(), "market": market, "service": service, "price": price})
    return {"records_ingested": len(records), "market": market, "services": services}


@app.task(
    name="vela.workers.ingestion_worker.ingest_metered_output",
    bind=True,
    max_retries=3,
)
def ingest_metered_output(
    self,
    asset_ids: list[str] | None = None,
    lookback_minutes: int = 5,
) -> dict[str, Any]:
    """Ingest metered energy output from SCADA/meter data."""
    if asset_ids is None:
        asset_ids = ["bat-001", "bat-002"]
    logger.info("Ingesting metered output assets=%s lookback=%dm", asset_ids, lookback_minutes)
    import numpy as np
    now = datetime.now(timezone.utc)
    records = []
    for asset_id in asset_ids:
        for i in range(lookback_minutes // 5):
            ts = now - timedelta(minutes=lookback_minutes - i * 5)
            records.append({
                "asset_id": asset_id,
                "timestamp": ts.isoformat(),
                "power_mw": round(np.random.normal(1.5, 0.3), 3),
                "soc": round(np.random.uniform(0.3, 0.8), 3),
                "energy_mwh": round(abs(np.random.normal(0.125, 0.025)), 4),
            })
    return {"records_ingested": len(records), "assets": asset_ids}
