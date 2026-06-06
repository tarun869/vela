"""Backfill forecast history by retroactively fitting and predicting over historical data."""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def backfill_forecasts(
    node: str = "TH_NP15_GEN-APND",
    start: datetime | None = None,
    end: datetime | None = None,
    history_days: int = 14,
    horizon_hours: int = 24,
    output: str = "backfill_forecasts.json",
) -> None:
    """
    Walk through each hour in [start, end] and generate a rolling forecast.
    Stores results as a JSON file with timestamps, mean, p10, p90.
    """
    from vela.m5_forecasting.price_forecast import ARPriceModel
    import numpy as np

    np.random.seed(42)
    now = datetime.now(timezone.utc)
    end = end or now
    start = start or (end - timedelta(days=7))

    daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]

    # Build full history for training
    full_history = []
    base = now - timedelta(days=history_days + 30)
    for i in range((history_days + 30) * 24):
        ts = base + timedelta(hours=i)
        price = max(0, daily[ts.hour % 24] + np.random.normal(0, 5))
        full_history.append(price)

    model = ARPriceModel(lags=24)
    model.fit(full_history)

    hours = max(1, int((end - start).total_seconds() / 3600))
    backfill_results = []

    logger.info("Backfilling %d forecast steps for node=%s", hours, node)
    for h in range(hours):
        forecast_time = start + timedelta(hours=h)
        idx = max(0, int((forecast_time - base).total_seconds() / 3600))
        recent = full_history[max(0, idx - 48) : idx] or full_history[:48]

        fc = model.predict(recent=recent, horizon=min(horizon_hours, 24))
        backfill_results.append({
            "node": node,
            "forecast_at": forecast_time.isoformat(),
            "horizon_hours": len(fc.mean),
            "mean": [round(v, 2) for v in fc.mean],
            "p10": [round(v, 2) for v in fc.p10],
            "p90": [round(v, 2) for v in fc.p90],
            "model": fc.model,
        })

    with open(output, "w") as f:
        json.dump(backfill_results, f, indent=2, default=str)
    logger.info("Backfill complete: %d records written to %s", len(backfill_results), output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vela Forecast Backfill")
    parser.add_argument("--node", default="TH_NP15_GEN-APND")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--output", default="backfill_forecasts.json")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    backfill_forecasts(
        node=args.node,
        start=now - timedelta(days=args.days),
        end=now,
        horizon_hours=args.horizon,
        output=args.output,
    )
