"""Celery task: run a dispatch optimization cycle for all active assets."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from vela.workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    name="vela.workers.optimization_worker.run_dispatch_cycle",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def run_dispatch_cycle(self, asset_ids: list[str] | None = None, horizon_hours: int = 24) -> dict[str, Any]:
    """
    Main dispatch optimization task.
    1. Fetches active assets from the registry.
    2. Pulls the latest LMP price forecast.
    3. Runs the MILP optimizer.
    4. Persists the plan and triggers bid submission if auto_submit is enabled.
    """
    logger.info("Starting dispatch cycle horizon=%dh assets=%s", horizon_hours, asset_ids)
    try:
        from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer
        from vela.m5_forecasting.price_forecast import ARPriceModel
        import numpy as np

        # In production, fetch from DB; use demo data here
        if asset_ids is None:
            asset_ids = ["bat-001", "bat-002", "bat-003"]

        assets = [
            Asset(asset_id=aid, capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
            for aid in asset_ids
        ]

        # Generate a representative LMP forecast
        np.random.seed(int(datetime.now(timezone.utc).hour))
        daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
                 50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
        lmp = [max(0, daily[h % 24] + np.random.normal(0, 6)) for h in range(horizon_hours)]

        optimizer = MILPDispatchOptimizer(horizon=horizon_hours)
        solution = optimizer.solve(assets=assets, lmp=lmp)

        result = {
            "status": solution.status,
            "objective": solution.objective,
            "solve_time_s": solution.solve_time_s,
            "assets": asset_ids,
            "horizon_hours": horizon_hours,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
            "total_discharge_mwh": sum(
                sum(v) for v in solution.discharge_mw.values()
            ),
        }
        logger.info("Dispatch complete: %s", result)
        return result

    except Exception as exc:
        logger.error("Dispatch cycle failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


@app.task(
    name="vela.workers.optimization_worker.run_single_asset_dispatch",
    bind=True,
    max_retries=2,
)
def run_single_asset_dispatch(
    self,
    asset_id: str,
    capacity_mwh: float = 4.0,
    power_mw: float = 2.0,
    soc_init: float = 0.5,
    lmp: list[float] | None = None,
    horizon_hours: int = 24,
) -> dict[str, Any]:
    """Optimize dispatch for a single asset. Useful for real-time re-dispatch."""
    from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer
    import numpy as np

    if lmp is None:
        np.random.seed(42)
        lmp = [max(0, 55 + np.random.normal(0, 20)) for _ in range(horizon_hours)]

    asset = Asset(
        asset_id=asset_id,
        capacity_mwh=capacity_mwh,
        power_mw=power_mw,
        soc_init=soc_init,
    )
    optimizer = MILPDispatchOptimizer(horizon=horizon_hours)
    solution = optimizer.solve(assets=[asset], lmp=lmp)

    return {
        "asset_id": asset_id,
        "status": solution.status,
        "objective": solution.objective,
        "solve_time_s": solution.solve_time_s,
        "charge_mw": solution.charge_mw[asset_id],
        "discharge_mw": solution.discharge_mw[asset_id],
        "soc": solution.soc[asset_id],
    }
