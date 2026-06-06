"""Data catalog: registry of datasets available in the Vela data platform."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass
class DatasetDescriptor:
    """Metadata about a registered dataset."""
    dataset_id: str
    name: str
    description: str
    category: Literal["market_prices", "metered_data", "forecasts", "settlements", "carbon", "weather"]
    source: str  # e.g., "CAISO_OASIS", "ERCOT_API", "internal"
    format: Literal["timeseries", "tabular", "json"] = "timeseries"
    granularity_minutes: int = 60
    schema: dict[str, str] = field(default_factory=dict)  # {column: dtype}
    location: str | None = None  # S3 path or DB table
    refresh_schedule: str | None = None  # cron expression
    last_refreshed: datetime | None = None
    tags: list[str] = field(default_factory=list)
    quality_score: float = 1.0  # 0-1, lower = known issues
    active: bool = True


class DataCatalog:
    """In-memory data catalog. In production this backs a database table."""

    def __init__(self) -> None:
        self._datasets: dict[str, DatasetDescriptor] = {}
        self._populate_defaults()

    def register(self, ds: DatasetDescriptor) -> None:
        self._datasets[ds.dataset_id] = ds

    def get(self, dataset_id: str) -> DatasetDescriptor | None:
        return self._datasets.get(dataset_id)

    def search(
        self,
        category: str | None = None,
        source: str | None = None,
        tags: list[str] | None = None,
        active_only: bool = True,
    ) -> list[DatasetDescriptor]:
        results = list(self._datasets.values())
        if active_only:
            results = [d for d in results if d.active]
        if category:
            results = [d for d in results if d.category == category]
        if source:
            results = [d for d in results if d.source == source]
        if tags:
            results = [d for d in results if any(t in d.tags for t in tags)]
        return results

    def _populate_defaults(self) -> None:
        defaults = [
            DatasetDescriptor(
                dataset_id="caiso_lmp_rt",
                name="CAISO Real-Time LMP",
                description="5-minute LMP prices for CAISO pricing nodes",
                category="market_prices",
                source="CAISO_OASIS",
                granularity_minutes=5,
                schema={"timestamp": "datetime", "node": "str", "lmp": "float", "energy": "float", "congestion": "float", "loss": "float"},
                location="s3://vela-data/caiso/lmp/rt/",
                refresh_schedule="*/5 * * * *",
                tags=["caiso", "lmp", "real_time"],
            ),
            DatasetDescriptor(
                dataset_id="caiso_lmp_da",
                name="CAISO Day-Ahead LMP",
                description="Hourly day-ahead LMP prices for CAISO",
                category="market_prices",
                source="CAISO_OASIS",
                granularity_minutes=60,
                location="s3://vela-data/caiso/lmp/da/",
                refresh_schedule="0 14 * * *",
                tags=["caiso", "lmp", "day_ahead"],
            ),
            DatasetDescriptor(
                dataset_id="ercot_spp_rt",
                name="ERCOT Real-Time Settlement Point Prices",
                description="15-minute real-time SPPs for ERCOT hubs and load zones",
                category="market_prices",
                source="ERCOT_API",
                granularity_minutes=15,
                location="s3://vela-data/ercot/spp/rt/",
                tags=["ercot", "spp", "real_time"],
            ),
            DatasetDescriptor(
                dataset_id="metered_telemetry",
                name="Asset Metered Output",
                description="5-minute metered energy and SOC telemetry for all assets",
                category="metered_data",
                source="internal",
                granularity_minutes=5,
                location="timescaledb://telemetry",
                tags=["telemetry", "metered"],
            ),
            DatasetDescriptor(
                dataset_id="price_forecasts",
                name="LMP Price Forecasts",
                description="Hourly price forecast outputs (mean, p10, p90)",
                category="forecasts",
                source="internal",
                granularity_minutes=60,
                location="timescaledb://price_forecasts",
                tags=["forecast", "lmp"],
            ),
        ]
        for ds in defaults:
            self.register(ds)


catalog = DataCatalog()
