"""Seed database with sample assets, sites, and market data."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SAMPLE_ASSETS = [
    {"asset_id": "bat-001", "asset_type": "battery", "capacity_mwh": 4.0, "power_mw": 2.0, "status": "online", "soc": 0.65, "site_id": "site-fresno"},
    {"asset_id": "bat-002", "asset_type": "battery", "capacity_mwh": 8.0, "power_mw": 4.0, "status": "online", "soc": 0.72, "site_id": "site-fresno"},
    {"asset_id": "bat-003", "asset_type": "battery", "capacity_mwh": 2.0, "power_mw": 1.0, "status": "standby", "soc": 0.50, "site_id": "site-bakersfield"},
    {"asset_id": "bat-004", "asset_type": "battery", "capacity_mwh": 12.0, "power_mw": 6.0, "status": "online", "soc": 0.85, "site_id": "site-bakersfield"},
    {"asset_id": "fly-001", "asset_type": "flywheel", "capacity_mwh": 0.1, "power_mw": 1.0, "status": "online", "soc": 0.90, "site_id": "site-fresno"},
]

SAMPLE_SITES = [
    {
        "site_id": "site-fresno",
        "name": "Fresno Solar+Storage Campus",
        "iso": "CAISO",
        "pricing_node": "TH_NP15_GEN-APND",
        "latitude": 36.7378,
        "longitude": -119.7871,
        "timezone": "America/Los_Angeles",
    },
    {
        "site_id": "site-bakersfield",
        "name": "Bakersfield Industrial VPP",
        "iso": "CAISO",
        "pricing_node": "TH_SP15_GEN-APND",
        "latitude": 35.3733,
        "longitude": -119.0187,
        "timezone": "America/Los_Angeles",
    },
]


def seed_lmp_data(days: int = 7) -> list[dict]:
    """Generate synthetic LMP history."""
    import numpy as np
    np.random.seed(42)
    daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    records = []
    for d in range(days):
        for h in range(24):
            ts = now - timedelta(days=days - d) + timedelta(hours=h)
            lmp = round(max(0, daily[h] + np.random.normal(0, 6)), 2)
            records.append({
                "timestamp": ts.isoformat(),
                "node": "TH_NP15_GEN-APND",
                "market": "CAISO",
                "lmp": lmp,
                "energy": round(lmp * 0.85, 2),
                "congestion": round(lmp * 0.10, 2),
                "loss": round(lmp * 0.05, 2),
            })
    return records


def seed_all() -> None:
    logger.info("Seeding assets (%d records)", len(SAMPLE_ASSETS))
    for asset in SAMPLE_ASSETS:
        logger.info("  Asset: %s (%s, %.1f MWh)", asset["asset_id"], asset["asset_type"], asset["capacity_mwh"])

    logger.info("Seeding sites (%d records)", len(SAMPLE_SITES))
    for site in SAMPLE_SITES:
        logger.info("  Site: %s (%s)", site["site_id"], site["name"])

    lmp_records = seed_lmp_data(days=7)
    logger.info("Seeded %d LMP records", len(lmp_records))
    logger.info("Data seeding complete.")


if __name__ == "__main__":
    seed_all()
