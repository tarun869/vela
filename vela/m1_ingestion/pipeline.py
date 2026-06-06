"""Market data ingestion pipeline."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Protocol

import httpx

logger = logging.getLogger(__name__)


@dataclass
class PricePoint:
    timestamp: datetime
    lmp: float          # $/MWh locational marginal price
    energy: float       # $/MWh energy component
    congestion: float   # $/MWh congestion component
    loss: float         # $/MWh loss component
    node: str


@dataclass
class AncillaryPrice:
    timestamp: datetime
    service: str        # "reg_up", "reg_down", "spin", "nonspin"
    price: float        # $/MW


@dataclass
class LoadPoint:
    timestamp: datetime
    load_mw: float
    region: str


@dataclass
class WeatherPoint:
    timestamp: datetime
    temperature_c: float
    wind_speed_ms: float
    irradiance_wm2: float
    humidity_pct: float
    location: str


class ISOConnector(Protocol):
    async def fetch_lmp(self, start: datetime, end: datetime, nodes: list[str]) -> list[PricePoint]: ...
    async def fetch_ancillary(self, start: datetime, end: datetime) -> list[AncillaryPrice]: ...


@dataclass
class IngestionPipeline:
    """Orchestrates data ingestion from multiple ISO connectors."""

    connectors: dict[str, ISOConnector] = field(default_factory=dict)
    _running: bool = field(default=False, init=False, repr=False)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list, init=False, repr=False)

    def register(self, market: str, connector: ISOConnector) -> None:
        """Register an ISO connector under a market name."""
        self.connectors[market] = connector
        logger.info("Registered connector for %s", market)

    def unregister(self, market: str) -> None:
        """Remove a registered connector."""
        self.connectors.pop(market, None)
        logger.info("Unregistered connector for %s", market)

    async def ingest_lmp(
        self,
        market: str,
        start: datetime,
        end: datetime,
        nodes: list[str],
    ) -> list[PricePoint]:
        """Fetch and return LMP data for a given market and time range."""
        if market not in self.connectors:
            raise KeyError(f"No connector registered for market: {market}")
        connector = self.connectors[market]
        prices = await connector.fetch_lmp(start, end, nodes)
        logger.info("Ingested %d LMP records from %s", len(prices), market)
        return prices

    async def ingest_ancillary(
        self,
        market: str,
        start: datetime,
        end: datetime,
    ) -> list[AncillaryPrice]:
        """Fetch ancillary service prices for a given market."""
        if market not in self.connectors:
            raise KeyError(f"No connector registered for market: {market}")
        connector = self.connectors[market]
        prices = await connector.fetch_ancillary(start, end)
        logger.info("Ingested %d ancillary records from %s", len(prices), market)
        return prices

    async def ingest_all_markets(
        self,
        start: datetime,
        end: datetime,
        nodes_by_market: dict[str, list[str]] | None = None,
    ) -> dict[str, list[PricePoint]]:
        """Concurrently ingest LMP from all registered markets."""
        nodes_by_market = nodes_by_market or {}
        tasks = {
            market: self.ingest_lmp(market, start, end, nodes_by_market.get(market, []))
            for market in self.connectors
        }
        results: dict[str, list[PricePoint]] = {}
        for market, coro in tasks.items():
            try:
                results[market] = await coro
            except Exception:
                logger.exception("Ingestion failed for market %s", market)
                results[market] = []
        return results

    async def run_continuous(
        self,
        interval_seconds: int = 300,
        nodes_by_market: dict[str, list[str]] | None = None,
    ) -> None:
        """Run ingestion in a loop at the given interval."""
        self._running = True
        nodes_by_market = nodes_by_market or {}
        logger.info("Starting continuous ingestion loop (interval=%ds)", interval_seconds)
        while self._running:
            now = datetime.now(timezone.utc)
            for market, connector in self.connectors.items():
                try:
                    prices = await connector.fetch_lmp(
                        now, now, nodes_by_market.get(market, [])
                    )
                    logger.debug("Polled %d LMP records from %s", len(prices), market)
                except Exception:
                    logger.exception("Ingestion failed for %s", market)
            await asyncio.sleep(interval_seconds)

    def stop(self) -> None:
        """Signal the continuous ingestion loop to stop."""
        self._running = False
        logger.info("Ingestion pipeline stop requested")

    async def stream_lmp(
        self,
        market: str,
        nodes: list[str],
        poll_interval: float = 5.0,
    ) -> AsyncIterator[PricePoint]:
        """Async generator that yields LMP price points as they arrive."""
        seen: set[tuple[datetime, str]] = set()
        while True:
            now = datetime.now(timezone.utc)
            try:
                prices = await self.ingest_lmp(market, now, now, nodes)
                for p in prices:
                    key = (p.timestamp, p.node)
                    if key not in seen:
                        seen.add(key)
                        yield p
            except Exception:
                logger.exception("Stream poll failed for %s", market)
            await asyncio.sleep(poll_interval)
