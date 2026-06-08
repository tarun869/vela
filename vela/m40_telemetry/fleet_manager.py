"""Fleet-wide coordinator over heterogeneous asset connectors.

Owns one :class:`AssetConnector` per asset, runs their telemetry streams
concurrently, keeps a live snapshot for the optimizer, fans dispatch decisions
out across connectors, and broadcasts telemetry/price updates to WebSocket
subscribers via non-blocking per-subscriber queues.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from vela.m39_extraction.models import ExtractedAsset

from .base import AssetConnector
from .generic_rest_connector import GenericRESTConnector
from .models import AssetTelemetry, IntegrationConfig, PriceTick
from .price_feed import ERCOTHistoricalReplay
from .simulator import BESSSimulator, SolarSimulator
from .sunspec_connector import SunSpecModbusConnector
from .tesla_connector import TeslaGatewayConnector

logger = logging.getLogger(__name__)

# Bounded so a slow/stalled subscriber can never back-pressure the telemetry loop.
_SUBSCRIBER_QUEUE_MAXSIZE = 256


def build_connector(config: IntegrationConfig) -> AssetConnector:
    """Instantiate the connector for a config; simulator if simulate/simulated."""
    params = config.extra_params
    rated_mw = float(params.get("rated_mw", 10.0))
    rated_mwh = float(params.get("rated_mwh", rated_mw * 4.0))
    chemistry = str(params.get("chemistry", "LFP"))

    if config.simulate or config.protocol == "simulated":
        return BESSSimulator(config.asset_id, rated_mw, rated_mwh, chemistry=chemistry)
    if config.protocol == "sunspec_modbus":
        return SunSpecModbusConnector(config, rated_mw, rated_mwh, chemistry=chemistry)
    if config.protocol == "tesla_gateway":
        return TeslaGatewayConnector(config, rated_mw, rated_mwh)
    if config.protocol == "generic_rest":
        return GenericRESTConnector(config)

    # ocpp / openadr not yet implemented — degrade gracefully to a simulator.
    logger.warning(
        "No connector for protocol %s (%s); using simulator", config.protocol, config.asset_id
    )
    return BESSSimulator(config.asset_id, rated_mw, rated_mwh, chemistry=chemistry)


class FleetManager:
    """Central coordinator the dispatch engine and WebSocket layer talk to."""

    def __init__(self, configs: list[IntegrationConfig]) -> None:
        self._configs = configs
        self.connectors: dict[str, AssetConnector] = {
            cfg.asset_id: build_connector(cfg) for cfg in configs
        }
        self._snapshot: dict[str, AssetTelemetry] = {}
        self._latest_price: PriceTick | None = None
        self._price_feed: ERCOTHistoricalReplay | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._tasks: list[asyncio.Task[None]] = []

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Connect every connector and launch their stream tasks concurrently."""
        for connector in self.connectors.values():
            self._tasks.append(asyncio.create_task(self._run_connector(connector)))
        if self._price_feed is not None:
            self._tasks.append(asyncio.create_task(self._run_price_feed(self._price_feed)))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for connector in self.connectors.values():
            await connector.disconnect()
        self._tasks.clear()

    async def _run_connector(self, connector: AssetConnector) -> None:
        try:
            await connector.connect()
            async for telemetry in connector.stream():
                self._snapshot[telemetry.asset_id] = telemetry
                self._broadcast({"type": "telemetry", "data": asdict(telemetry)})
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one bad connector must not kill the fleet
            logger.exception("Connector %s stream crashed", connector.asset_id)

    async def _run_price_feed(self, feed: ERCOTHistoricalReplay) -> None:
        try:
            async for tick in feed.stream():
                self._latest_price = tick
                self._broadcast({"type": "price", "data": asdict(tick)})
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Price feed crashed")

    # --- optimizer / dispatch surface ------------------------------------

    async def get_fleet_state(self) -> dict[str, Any]:
        """Current telemetry snapshot for all assets (used by the optimizer)."""
        return {
            "assets": {aid: asdict(t) for aid, t in self._snapshot.items()},
            "price": asdict(self._latest_price) if self._latest_price else None,
        }

    async def send_fleet_dispatch(self, decisions: list[dict[str, Any]]) -> dict[str, bool]:
        """Apply ``[{asset_id, mw}, ...]`` across connectors; return per-asset success."""
        results: dict[str, bool] = {}
        for decision in decisions:
            asset_id = decision["asset_id"]
            connector = self.connectors.get(asset_id)
            if connector is None:
                results[asset_id] = False
                continue
            results[asset_id] = await connector.send_dispatch(float(decision["mw"]))
        return results

    # --- websocket broadcast ---------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a subscriber; primes it with the current snapshot + price."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
        for telemetry in self._snapshot.values():
            queue.put_nowait({"type": "telemetry", "data": asdict(telemetry)})
        if self._latest_price is not None:
            queue.put_nowait({"type": "price", "data": asdict(self._latest_price)})
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def _broadcast(self, message: dict[str, Any]) -> None:
        """Non-blocking fan-out; drops messages to full (stalled) subscribers."""
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.debug("Subscriber queue full; dropping message")

    def broadcast(self, message: dict[str, Any]) -> None:
        """Public fan-out hook for other modules (e.g. the dispatch scheduler)."""
        self._broadcast(message)

    # --- factory ----------------------------------------------------------

    @classmethod
    def from_demo_fleet(cls, extracted_assets: list[ExtractedAsset]) -> FleetManager:
        """Build an all-simulated fleet from extraction output + ERCOT price replay."""
        manager = cls.__new__(cls)
        manager._configs = []
        manager._snapshot = {}
        manager._latest_price = None
        manager._subscribers = set()
        manager._tasks = []
        manager.connectors = {}

        for asset in extracted_assets:
            if asset.asset_type == "Solar":
                manager.connectors[asset.asset_id] = SolarSimulator(
                    asset.asset_id, asset.rated_mw, tick_interval_seconds=1.0
                )
            else:
                manager.connectors[asset.asset_id] = BESSSimulator(
                    asset.asset_id,
                    asset.rated_mw,
                    asset.rated_mwh or asset.rated_mw * 4.0,
                    chemistry=asset.chemistry or "LFP",
                    tick_interval_seconds=1.0,
                )

        manager._price_feed = ERCOTHistoricalReplay(
            date="2023-08-10", node="HB_HUBZONE", speed_multiplier=30.0
        )
        return manager
