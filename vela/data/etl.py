"""ETL pipelines for market data, telemetry, and settlement ingestion."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)


@dataclass
class ETLJob:
    """Metadata and configuration for a single ETL job."""
    job_id: str
    name: str
    source: str
    destination: str
    transform_fn: Callable | None = None
    batch_size: int = 1000
    retry_attempts: int = 3
    dry_run: bool = False

    def run(self, records: list[dict]) -> "ETLResult":
        return run_job(self, records)


@dataclass
class ETLResult:
    job_id: str
    records_read: int = 0
    records_written: int = 0
    records_failed: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.records_failed == 0 and self.completed_at is not None


def run_job(job: ETLJob, records: list[dict]) -> ETLResult:
    """Execute a single ETL job against a list of records."""
    result = ETLResult(job_id=job.job_id)
    result.records_read = len(records)

    for i in range(0, len(records), job.batch_size):
        batch = records[i : i + job.batch_size]
        transformed = []
        for record in batch:
            try:
                out = job.transform_fn(record) if job.transform_fn else record
                if out is not None:
                    transformed.append(out)
            except Exception as exc:
                result.records_failed += 1
                result.errors.append(f"Transform error: {exc}")

        if not job.dry_run:
            result.records_written += len(transformed)
            logger.debug("ETL %s: wrote %d records to %s", job.name, len(transformed), job.destination)

    result.completed_at = datetime.now(timezone.utc)
    return result


def caiso_lmp_transform(raw: dict) -> dict:
    """Transform a raw CAISO OASIS row into the internal LMP schema."""
    return {
        "timestamp": raw.get("INTERVALSTARTTIME_GMT") or raw.get("timestamp"),
        "node": raw.get("NODE") or raw.get("node"),
        "lmp": float(raw.get("MW", raw.get("lmp", 0))),
        "energy": float(raw.get("ENERGY_MW", raw.get("energy", 0))),
        "congestion": float(raw.get("CONGESTION_MW", raw.get("congestion", 0))),
        "loss": float(raw.get("LOSS_MW", raw.get("loss", 0))),
        "market": "CAISO",
    }


def ercot_spp_transform(raw: dict) -> dict:
    """Transform a raw ERCOT SPP row into the internal price schema."""
    return {
        "timestamp": raw.get("DeliveryDate") or raw.get("timestamp"),
        "node": raw.get("SettlementPoint") or raw.get("node"),
        "lmp": float(raw.get("SettlementPointPrice", raw.get("spp", 0))),
        "energy": float(raw.get("SettlementPointPrice", 0)),
        "congestion": 0.0,
        "loss": 0.0,
        "market": "ERCOT",
    }


def telemetry_transform(raw: dict) -> dict:
    """Validate and normalize a raw SCADA telemetry record."""
    soc = raw.get("soc")
    if soc is not None:
        soc = max(0.0, min(1.0, float(soc)))
    return {
        "asset_id": str(raw.get("asset_id", "")),
        "timestamp": raw.get("timestamp"),
        "soc": soc,
        "power_mw": float(raw.get("power_mw", 0)),
        "temperature_c": raw.get("temperature_c"),
        "status": raw.get("status", "unknown"),
    }


def settlement_transform(raw: dict) -> dict:
    """Normalize a settlement record from any ISO format."""
    return {
        "asset_id": str(raw.get("asset_id", "")),
        "market": str(raw.get("market", "UNKNOWN")),
        "interval_start": raw.get("interval_start") or raw.get("timestamp"),
        "scheduled_mwh": float(raw.get("scheduled_mwh", raw.get("scheduled", 0))),
        "metered_mwh": float(raw.get("metered_mwh", raw.get("metered", 0))),
        "lmp": float(raw.get("lmp", 0)),
    }


def batch_records(records: list[Any], batch_size: int) -> Iterator[list[Any]]:
    """Yield records in batches of batch_size."""
    for i in range(0, len(records), batch_size):
        yield records[i : i + batch_size]
