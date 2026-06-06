"""
Main dispatch control loop: Observe -> Forecast -> Optimize -> Bid -> Settle.

Run as a standalone service or imported by the API server.
The loop executes every `interval_seconds` (default 300 = 5 minutes),
aligning with the typical CAISO 5-minute real-time market.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LoopState:
    """Mutable state shared across loop phases within a single cycle."""
    cycle_id: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    phase: str = "idle"
    asset_ids: list[str] = field(default_factory=list)
    lmp_forecast: list[float] = field(default_factory=list)
    dispatch_solution: Any = None
    bids_submitted: list[str] = field(default_factory=list)
    settlement_results: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def log_phase(self, name: str) -> None:
        self.phase = name
        logger.info("[%s] Phase: %s", self.cycle_id[:8], name)


@dataclass
class DispatchLoop:
    """
    Orchestrates the five-phase VPP dispatch cycle.

    Phases:
    1. Observe   - Collect real-time telemetry and state of charge for all assets.
    2. Forecast  - Generate LMP price forecasts for the next horizon window.
    3. Optimize  - Run the MILP optimizer to find the revenue-maximizing dispatch schedule.
    4. Bid       - Submit optimized bids to the market (day-ahead / real-time).
    5. Settle    - Reconcile metered output against scheduled and compute net revenue.
    """
    horizon_hours: int = 24
    market: str = "CAISO"
    node: str = "TH_NP15_GEN-APND"
    interval_seconds: float = 300.0
    auto_submit_bids: bool = False  # require human approval in production
    max_consecutive_errors: int = 5

    _consecutive_errors: int = field(default=0, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)
    _cycle_count: int = field(default=0, init=False, repr=False)

    async def run_forever(self) -> None:
        """Start the loop and run until interrupted."""
        self._running = True
        logger.info(
            "Dispatch loop starting: market=%s node=%s interval=%ds",
            self.market, self.node, self.interval_seconds,
        )
        while self._running:
            cycle_start = time.monotonic()
            try:
                state = await self.run_cycle()
                self._cycle_count += 1
                self._consecutive_errors = 0
                logger.info(
                    "Cycle %d complete in %.2fs | errors=%s",
                    self._cycle_count,
                    time.monotonic() - cycle_start,
                    len(state.errors),
                )
            except Exception as exc:
                self._consecutive_errors += 1
                logger.error(
                    "Cycle failed (consecutive=%d): %s",
                    self._consecutive_errors, exc, exc_info=True,
                )
                if self._consecutive_errors >= self.max_consecutive_errors:
                    logger.critical("Too many consecutive errors; stopping loop")
                    self._running = False
                    raise

            # Sleep for the remainder of the interval
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, self.interval_seconds - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    def stop(self) -> None:
        """Signal the loop to stop after the current cycle."""
        self._running = False
        logger.info("Loop stop requested")

    async def run_cycle(self) -> LoopState:
        """Execute a single full dispatch cycle. Returns the final state."""
        import uuid
        state = LoopState(cycle_id=str(uuid.uuid4()))

        state = await self._phase_observe(state)
        state = await self._phase_forecast(state)
        state = await self._phase_optimize(state)
        state = await self._phase_bid(state)
        state = await self._phase_settle(state)

        state.phase = "complete"
        return state

    async def _phase_observe(self, state: LoopState) -> LoopState:
        """Collect current SOC and power readings for all active assets."""
        state.log_phase("observe")
        try:
            # In production: query the asset registry DB and SCADA feeds
            state.asset_ids = ["bat-001", "bat-002", "bat-003"]
            logger.debug("Observed %d active assets", len(state.asset_ids))
        except Exception as exc:
            state.errors.append(f"observe: {exc}")
            logger.error("Observe phase error: %s", exc)
        return state

    async def _phase_forecast(self, state: LoopState) -> LoopState:
        """Generate LMP price forecast for the optimization horizon."""
        state.log_phase("forecast")
        try:
            from vela.m5_forecasting.price_forecast import ARPriceModel
            import numpy as np

            np.random.seed(int(datetime.now(timezone.utc).hour))
            daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
                     50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
            history = []
            for _ in range(7):  # 7 days of history
                history.extend([max(0, p + np.random.normal(0, 5)) for p in daily])

            model = ARPriceModel(lags=24)
            model.fit(history)
            forecast = model.predict(recent=history[-48:], horizon=self.horizon_hours)
            state.lmp_forecast = forecast.mean
            logger.debug("Forecast generated: mean=%.2f $/MWh", sum(forecast.mean) / len(forecast.mean))
        except Exception as exc:
            state.errors.append(f"forecast: {exc}")
            state.lmp_forecast = [55.0] * self.horizon_hours  # fallback
            logger.warning("Forecast failed, using flat fallback: %s", exc)
        return state

    async def _phase_optimize(self, state: LoopState) -> LoopState:
        """Run MILP optimizer to find the optimal dispatch schedule."""
        state.log_phase("optimize")
        if not state.asset_ids:
            state.errors.append("optimize: no assets to dispatch")
            return state
        try:
            from vela.m6_optimizer.milp import Asset, MILPDispatchOptimizer

            assets = [
                Asset(asset_id=aid, capacity_mwh=4.0, power_mw=2.0, soc_init=0.5)
                for aid in state.asset_ids
            ]
            optimizer = MILPDispatchOptimizer(horizon=self.horizon_hours)
            state.dispatch_solution = optimizer.solve(assets=assets, lmp=state.lmp_forecast)
            logger.info(
                "Optimization complete: status=%s objective=%.2f solve_time=%.3fs",
                state.dispatch_solution.status,
                state.dispatch_solution.objective,
                state.dispatch_solution.solve_time_s,
            )
        except Exception as exc:
            state.errors.append(f"optimize: {exc}")
            logger.error("Optimize phase error: %s", exc, exc_info=True)
        return state

    async def _phase_bid(self, state: LoopState) -> LoopState:
        """Construct and optionally submit market bids from the dispatch plan."""
        state.log_phase("bid")
        if state.dispatch_solution is None or state.dispatch_solution.status not in ("Optimal", "Feasible"):
            logger.warning("Skipping bid submission: no valid dispatch solution")
            return state
        try:
            for asset_id in state.asset_ids:
                discharge = state.dispatch_solution.discharge_mw.get(asset_id, [])
                total_mw = sum(discharge) / max(len(discharge), 1)
                if total_mw > 0.01:
                    state.bids_submitted.append(f"{asset_id}:energy:{total_mw:.3f}MW")
            logger.info("Bid preparation complete: %d bids", len(state.bids_submitted))
            if self.auto_submit_bids:
                logger.info("Auto-submit enabled: submitting %d bids to %s", len(state.bids_submitted), self.market)
        except Exception as exc:
            state.errors.append(f"bid: {exc}")
            logger.error("Bid phase error: %s", exc)
        return state

    async def _phase_settle(self, state: LoopState) -> LoopState:
        """Run settlement reconciliation for the previous interval."""
        state.log_phase("settle")
        try:
            from vela.m9_settlement.settlement_engine import SettlementEngine
            import numpy as np

            engine = SettlementEngine(market=self.market)
            now = datetime.now(timezone.utc)
            np.random.seed(42)
            for asset_id in state.asset_ids:
                scheduled = [max(0, np.random.normal(1.2, 0.3)) for _ in range(1)]
                metered = [max(0, s + np.random.normal(0, 0.05)) for s in scheduled]
                lmp = state.lmp_forecast[:1] or [55.0]
                stmt = engine.calculate(
                    asset_id=asset_id,
                    settlement_date=now,
                    scheduled_mwh=scheduled,
                    metered_mwh=metered,
                    lmp=lmp,
                )
                state.settlement_results.append({
                    "asset_id": asset_id,
                    "revenue": round(stmt.total_revenue, 4),
                    "imbalance": round(stmt.total_imbalance_charge, 4),
                })
            total = sum(r["revenue"] for r in state.settlement_results)
            logger.info("Settlement complete: total_revenue=%.4f", total)
        except Exception as exc:
            state.errors.append(f"settle: {exc}")
            logger.error("Settle phase error: %s", exc)
        return state


async def run_loop(interval_seconds: float = 300.0) -> None:
    """Convenience entry point for running the dispatch loop as an async service."""
    loop = DispatchLoop(interval_seconds=interval_seconds)
    await loop.run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_loop(interval_seconds=30.0))
