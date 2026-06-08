"""Settlement tracker: accumulates dispatch events throughout the day,
computes end-of-day P&L vs baseline, verifies obligation compliance.

Call :meth:`record_price_tick` on every LMP update so :meth:`generate_summary`
can compute a meaningful full-day baseline comparison. Call
:meth:`record_soh_snapshot` at day-open (``is_start=True``) and day-close to
populate the :attr:`SettlementSummary.soh_delta_by_asset` field.
"""
from __future__ import annotations

from datetime import datetime, timezone

from vela.m39_extraction.models import ExtractedObligation
from vela.m41_optimizer.heuristic import INTERVAL_HOURS, degradation_cost_per_mwh
from vela.m41_optimizer.models import DispatchDecision

from .models import DispatchRecord, ObligationRecord, SettlementSummary

BASELINE_DISCHARGE_LMP = 120.0
BASELINE_CHARGE_LMP = 40.0
BASELINE_CHARGE_FRACTION = 0.5


class SettlementTracker:
    """Accumulates dispatch and obligation events; produces settlement summaries."""

    def __init__(self, fleet_capacity_mw: float = 0.0) -> None:
        self._fleet_capacity_mw = fleet_capacity_mw
        self._dispatch_records: list[DispatchRecord] = []
        self._obligation_records: list[ObligationRecord] = []
        self._all_lmps: list[float] = []
        self._soh_start: dict[str, float] = {}
        self._soh_current: dict[str, float] = {}
        self._date = datetime.now(timezone.utc).date().isoformat()

    @property
    def dispatch_records(self) -> list[DispatchRecord]:
        return list(self._dispatch_records)

    def record_price_tick(self, lmp: float) -> None:
        """Register an LMP observation for full-day baseline computation."""
        self._all_lmps.append(lmp)

    def record_dispatch(
        self,
        decision: DispatchDecision,
        lmp: float,
        *,
        rated_mwh: float | None = None,
        warranty_cycles: int = 6000,
        soh_pct: float = 100.0,
    ) -> None:
        """Record one 5-minute dispatch interval outcome."""
        mw = decision.recommended_mw
        revenue = round(mw * lmp * INTERVAL_HOURS, 4)
        eff_rated_mwh = rated_mwh if rated_mwh is not None else max(abs(mw), 0.001) * 4.0
        deg_per_mwh = degradation_cost_per_mwh(
            max(eff_rated_mwh, 0.001), warranty_cycles, soh_pct
        )
        deg_cost = round(abs(mw) * INTERVAL_HOURS * deg_per_mwh, 4)
        self._dispatch_records.append(
            DispatchRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                asset_id=decision.asset_id,
                dispatched_mw=mw,
                lmp_at_dispatch=lmp,
                revenue_usd=revenue,
                degradation_cost_usd=deg_cost,
                net_value_usd=round(revenue - deg_cost, 4),
            )
        )

    def record_soh_snapshot(
        self, asset_id: str, soh_pct: float, *, is_start: bool = False
    ) -> None:
        """Register an SOH snapshot; call with is_start=True at day-open."""
        if is_start or asset_id not in self._soh_start:
            self._soh_start[asset_id] = soh_pct
        self._soh_current[asset_id] = soh_pct

    def record_obligation_window(
        self,
        obligation: ExtractedObligation,
        delivered_mw: float,
        *,
        obligation_id: str | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
    ) -> None:
        """Record compliance for one obligation delivery window."""
        compliant = delivered_mw >= obligation.committed_mw
        if compliant:
            penalty = 0.0
        else:
            shortfall = obligation.committed_mw - delivered_mw
            rate = obligation.penalty_linear_per_mwh or 0.0
            penalty = round(shortfall * rate, 4)

        ts = datetime.now(timezone.utc).isoformat()
        self._obligation_records.append(
            ObligationRecord(
                obligation_id=obligation_id or obligation.obligation_type,
                window_start=window_start or ts,
                window_end=window_end or ts,
                committed_mw=obligation.committed_mw,
                delivered_mw=delivered_mw,
                compliant=compliant,
                penalty_usd=penalty,
            )
        )

    def compute_baseline(
        self,
        all_lmp_values: list[float],
        fleet_capacity_mw: float,
    ) -> float:
        """Return the revenue a simple threshold strategy would have made.

        Discharges at full capacity when LMP > $120, charges at 50% capacity
        when LMP < $40, holds otherwise.
        """
        total = 0.0
        for lmp in all_lmp_values:
            if lmp > BASELINE_DISCHARGE_LMP:
                total += fleet_capacity_mw * lmp * INTERVAL_HOURS
            elif lmp < BASELINE_CHARGE_LMP:
                # Cost of buying energy at this LMP (negative revenue when LMP > 0).
                total -= fleet_capacity_mw * BASELINE_CHARGE_FRACTION * lmp * INTERVAL_HOURS
        return round(total, 2)

    def generate_summary(self) -> SettlementSummary:
        """Aggregate all records into a :class:`SettlementSummary`."""
        total_rev = sum(r.revenue_usd for r in self._dispatch_records)
        total_deg = sum(r.degradation_cost_usd for r in self._dispatch_records)
        total_pen = sum(r.penalty_usd for r in self._obligation_records)
        net = round(total_rev - total_deg, 2)

        lmps = self._all_lmps if self._all_lmps else [
            r.lmp_at_dispatch for r in self._dispatch_records
        ]
        fleet_cap = self._fleet_capacity_mw or self._infer_fleet_capacity()
        baseline = self.compute_baseline(lmps, fleet_cap)

        outperformance = round(net - baseline, 2)
        outperf_pct = round(
            (outperformance / abs(baseline) * 100.0) if baseline != 0.0 else 0.0, 2
        )

        soh_delta = {
            aid: round(self._soh_current.get(aid, self._soh_start[aid]) - start, 4)
            for aid, start in self._soh_start.items()
        }

        return SettlementSummary(
            date=self._date,
            total_revenue_usd=round(total_rev, 2),
            total_degradation_cost_usd=round(total_deg, 2),
            total_penalties_usd=round(total_pen, 2),
            net_value_usd=net,
            baseline_revenue_usd=baseline,
            outperformance_usd=outperformance,
            outperformance_pct=outperf_pct,
            obligation_records=list(self._obligation_records),
            all_obligations_compliant=all(r.compliant for r in self._obligation_records),
            soh_delta_by_asset=soh_delta,
        )

    def _infer_fleet_capacity(self) -> float:
        """Estimate fleet capacity from the peak aggregate dispatch."""
        if not self._dispatch_records:
            return 1.0
        by_ts: dict[str, float] = {}
        for r in self._dispatch_records:
            by_ts[r.timestamp] = by_ts.get(r.timestamp, 0.0) + abs(r.dispatched_mw)
        return max(by_ts.values())
