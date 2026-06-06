"""Celery application configuration."""
from __future__ import annotations

from celery import Celery

app = Celery(
    "vela",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
    include=[
        "vela.workers.optimization_worker",
        "vela.workers.settlement_worker",
        "vela.workers.ingestion_worker",
        "vela.workers.ml_worker",
        "vela.workers.notification_worker",
    ],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    beat_schedule={
        "run-dispatch-every-5-min": {
            "task": "vela.workers.optimization_worker.run_dispatch_cycle",
            "schedule": 300.0,
        },
        "run-settlement-hourly": {
            "task": "vela.workers.settlement_worker.calculate_settlement",
            "schedule": 3600.0,
        },
        "retrain-models-daily": {
            "task": "vela.workers.ml_worker.retrain_forecast_models",
            "schedule": 86400.0,
        },
    },
)
