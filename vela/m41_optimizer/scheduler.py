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
from vela.m42_settlement.api import set_tracker
from vela.m42_settlement.tracker import SettlementTracker

from .heuristic import _window_active, detect_spike
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
        self._tracker: SettlementTracker | None = None
        # Running max delivered MW per obligation_id over its active window, so
        # the settlement record reflects the best coverage we actually held.
        self._obligation_delivered: dict[str, float] = {}

    @property
    def last_plan(self) -> FleetDispatchPlan | None:
        return self._last_plan

    @property
    def tracker(self) -> SettlementTracker | None:
        return self._tracker

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

        # Stand up a settlement tracker for this session and register it so the
        # /api/v1/settlement endpoints serve live P&L as the fleet runs.
        tracker = SettlementTracker(fleet_capacity_mw=self._fleet_capacity())
        committed = sum(o.committed_mw for o in self._obligations)
        penalty_rate = max(
            (o.penalty_linear_per_mwh or 0.0 for o in self._obligations), default=0.0
        )
        tracker.configure_baseline(committed, penalty_rate)
        self._tracker = tracker
        set_tracker(tracker)
        await self._seed_start_soh()

        self._tasks.append(asyncio.create_task(self._optimize_loop()))
        self._tasks.append(asyncio.create_task(self._spike_loop()))

    async def _seed_start_soh(self) -> None:
        """Record day-open SOH for every asset so settlement can show drift."""
        assert self._fleet is not None and self._tracker is not None
        state = await self._fleet.get_fleet_state()
        for asset_id, telemetry in state.get("assets", {}).items():
            self._tracker.record_soh_snapshot(
                asset_id, float(telemetry.get("soh_pct", 100.0)), is_start=True
            )

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
        self._record_settlement(plan, fleet_state, current_lmp, current_hour)
        self._fleet.broadcast({"type": "dispatch_plan", "data": asdict(plan)})
        for status in plan.obligations_status:
            if status.status in ("AT_RISK", "BREACHED"):
                self._fleet.broadcast({"type": "obligation_alert", "data": asdict(status)})

    def _record_settlement(
        self,
        plan: FleetDispatchPlan,
        fleet_state: dict[str, Any],
        current_lmp: float,
        current_hour: int,
    ) -> None:
        """Push this interval's dispatch, SOH and obligation coverage to the tracker."""
        if self._tracker is None:
            return
        assets = fleet_state.get("assets", {})
        for decision in plan.decisions:
            spec = assets.get(decision.asset_id, {})
            soh = float(spec.get("soh_pct", 100.0))
            self._tracker.record_dispatch(
                decision,
                current_lmp,
                rated_mwh=spec.get("rated_mwh"),
                warranty_cycles=int(spec.get("warranty_cycles", 6000)),
                soh_pct=soh,
            )
            self._tracker.record_soh_snapshot(decision.asset_id, soh)

        # Upsert obligation coverage for any obligation currently in its window,
        # keeping the best (max) coverage we held during the window.
        status_by_id = {s.obligation_id: s for s in plan.obligations_status}
        day = self._date_from_price(fleet_state.get("price"))
        for i, obligation in enumerate(self._obligations):
            if not _window_active(obligation, current_hour):
                continue
            oid = f"{obligation.obligation_type}-{i}"
            status = status_by_id.get(oid)
            covered = status.currently_covered_mw if status else 0.0
            # Credit the firm-capacity value of the MW reserved this interval.
            self._tracker.record_capacity_value(covered, current_lmp)
            best = max(self._obligation_delivered.get(oid, 0.0), covered)
            self._obligation_delivered[oid] = best
            window = obligation.delivery_windows[0] if obligation.delivery_windows else None
            ws = f"{day}T{window.start_hour:02d}:00:00+00:00" if window else None
            we = f"{day}T{window.end_hour:02d}:00:00+00:00" if window else None
            self._tracker.record_obligation_window(
                obligation, best, obligation_id=oid, window_start=ws, window_end=we
            )

    async def _spike_loop(self) -> None:
        assert self._fleet is not None
        queue = self._fleet.subscribe()
        try:
            while True:
                message = await queue.get()
                if message.get("type") != "price":
                    continue
                lmp = float(message["data"]["lmp_per_mwh"])
                if self._tracker is not None:
                    self._tracker.record_price_tick(lmp)
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

    @staticmethod
    def _date_from_price(price: dict[str, Any] | None) -> str:
        if price and price.get("timestamp"):
            try:
                return datetime.fromisoformat(price["timestamp"]).date().isoformat()
            except ValueError:
                pass
        return datetime.now(timezone.utc).date().isoformat()
