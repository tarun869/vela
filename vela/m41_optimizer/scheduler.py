"""Periodic dispatch scheduler driving the optimizer and broadcasting plans.

Runs :meth:`DispatchOptimizer.optimize` on a fixed cadence (5 min in prod, or an
accelerated demo pace), applies the resulting decisions through the
:class:`~vela.m40_telemetry.fleet_manager.FleetManager`, and broadcasts the plan
plus any obligation alerts. Price spikes are detected on *every* incoming
PriceTick, independently of the 5-minute loop.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from vela.m39_extraction.models import ExtractedObligation
from vela.m40_telemetry.fleet_manager import FleetManager

from .heuristic import detect_spike
from .interface import DispatchOptimizer
from .models import FleetDispatchPlan

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 300.0  # 5 minutes


class _Override:
    __slots__ = ("mw", "reason")

    def __init__(self, mw: float, reason: str) -> None:
        self.mw = mw
        self.reason = reason


class DispatchScheduler:
    """Coordinates the optimizer, fleet dispatch, and WebSocket broadcasts."""

    def __init__(self) -> None:
        self._fleet: FleetManager | None = None
        self._optimizer: DispatchOptimizer | None = None
        self._obligations: list[ExtractedObligation] = []
        self._interval_seconds = DEFAULT_INTERVAL_SECONDS
        self._tasks: list[asyncio.Task[None]] = []
        self._overrides: dict[str, _Override] = {}
        self._last_plan: FleetDispatchPlan | None = None
        self._prev_lmp: float | None = None

    @property
    def last_plan(self) -> FleetDispatchPlan | None:
        return self._last_plan

    async def start(
        self,
        fleet_manager: FleetManager,
        optimizer: DispatchOptimizer,
        price_feed: Any | None = None,  # noqa: ARG002 - prices arrive via the fleet bus
        obligations: list[ExtractedObligation] | None = None,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._fleet = fleet_manager
        self._optimizer = optimizer
        self._obligations = obligations or []
        self._interval_seconds = interval_seconds
        self._tasks.append(asyncio.create_task(self._optimize_loop()))
        self._tasks.append(asyncio.create_task(self._spike_loop()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    def set_override(self, asset_id: str, mw: float, reason: str) -> None:
        """Register a one-shot manual override for the next dispatch decision."""
        self._overrides[asset_id] = _Override(mw, reason)

    # --- internal loops ---------------------------------------------------

    async def _optimize_loop(self) -> None:
        assert self._fleet is not None and self._optimizer is not None
        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad cycle must not stop the loop
                logger.exception("Dispatch optimize cycle failed")
            await asyncio.sleep(self._interval_seconds)

    async def _run_once(self) -> None:
        assert self._fleet is not None and self._optimizer is not None
        fleet_state = await self._build_fleet_state()
        price = fleet_state.get("price")
        current_lmp = float(price["lmp_per_mwh"]) if price else 0.0
        current_hour = self._hour_from_price(price)

        plan = await self._optimizer.optimize(
            fleet_state, current_lmp, self._obligations, current_hour
        )
        self._apply_overrides(plan)
        self._last_plan = plan

        await self._fleet.send_fleet_dispatch(
            [{"asset_id": d.asset_id, "mw": d.recommended_mw} for d in plan.decisions]
        )
        self._fleet.broadcast({"type": "dispatch_plan", "data": asdict(plan)})
        for status in plan.obligations_status:
            if status.status in ("AT_RISK", "BREACHED"):
                self._fleet.broadcast({"type": "obligation_alert", "data": asdict(status)})

    async def _spike_loop(self) -> None:
        assert self._fleet is not None
        queue = self._fleet.subscribe()
        try:
            while True:
                message = await queue.get()
                if message.get("type") != "price":
                    continue
                lmp = float(message["data"]["lmp_per_mwh"])
                if self._prev_lmp is not None:
                    alert = detect_spike(
                        lmp,
                        self._prev_lmp,
                        available_mw=self._fleet_capacity(),
                        upcoming_obligation_mw=sum(o.committed_mw for o in self._obligations),
                    )
                    if alert is not None:
                        self._fleet.broadcast({"type": "spike_alert", "data": asdict(alert)})
                self._prev_lmp = lmp
        except asyncio.CancelledError:
            raise
        finally:
            self._fleet.unsubscribe(queue)

    # --- helpers ----------------------------------------------------------

    async def _build_fleet_state(self) -> dict[str, Any]:
        """Merge live telemetry with each connector's static asset spec."""
        assert self._fleet is not None
        state = await self._fleet.get_fleet_state()
        merged: dict[str, Any] = {}
        for asset_id, telemetry in state.get("assets", {}).items():
            connector = self._fleet.connectors.get(asset_id)
            merged[asset_id] = {
                **telemetry,
                "rated_mw": getattr(connector, "rated_mw", 10.0),
                "rated_mwh": getattr(connector, "rated_mwh", None)
                or getattr(connector, "rated_mw", 10.0) * 4.0,
                "chemistry": getattr(connector, "chemistry", "LFP"),
                "warranty_cycles": 6000,
            }
        return {"assets": merged, "price": state.get("price")}

    def _fleet_capacity(self) -> float:
        assert self._fleet is not None
        return sum(
            float(getattr(c, "rated_mw", 0.0)) for c in self._fleet.connectors.values()
        )

    def _apply_overrides(self, plan: FleetDispatchPlan) -> None:
        if not self._overrides:
            return
        for decision in plan.decisions:
            override = self._overrides.get(decision.asset_id)
            if override is None:
                continue
            decision.recommended_mw = override.mw
            decision.reasoning = f"MANUAL OVERRIDE: {override.reason}"
            decision.binding_constraint = None
        self._overrides.clear()

    @staticmethod
    def _hour_from_price(price: dict[str, Any] | None) -> int:
        if price and price.get("timestamp"):
            try:
                return datetime.fromisoformat(price["timestamp"]).hour
            except ValueError:
                pass
        return datetime.now(timezone.utc).hour
