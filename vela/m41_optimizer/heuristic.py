"""Heuristic, fully-explainable dispatch engine (demo-grade).

Implements a transparent rule-based optimizer: a price signal sets the action,
SOH-ranked allocation routes power to the healthiest assets, and every reduction
from the unconstrained ideal is attributed to a named, dollar-costed constraint.
A future MILP can replace it behind :class:`DispatchOptimizer`.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from vela.m39_extraction.models import ExtractedObligation

from .interface import DispatchOptimizer
from .models import (
    DispatchDecision,
    FleetDispatchPlan,
    ObligationStatus,
    SpikeAlert,
)

# --- tunable constants -------------------------------------------------------
DISCHARGE_LMP = 150.0  # above this: discharge
CHARGE_LMP = 40.0  # below this: charge
INTERVAL_HOURS = 5.0 / 60.0  # one dispatch interval
THERMAL_THRESHOLD_C = 35.0
THERMAL_DERATE = 0.70  # derate to 70% of rated power when hot
SOC_FLOOR_PCT = 5.0
WARRANTY_REPLACEMENT_USD_PER_MWH = 280_000.0  # 2025 BESS replacement cost
NEXT_BEST_REVENUE = CHARGE_LMP  # opportunity-cost baseline for reservations
AT_RISK_BUFFER = 0.10  # < 10% headroom => obligation at risk


def _deg_multiplier(soh_pct: float) -> float:
    if soh_pct > 80.0:
        return 1.0
    if soh_pct >= 70.0:
        return 1.5
    return 2.5


def degradation_cost_per_mwh(rated_mwh: float, warranty_cycles: int, soh_pct: float) -> float:
    """Marginal degradation cost ($/MWh of throughput) for an asset."""
    replacement_value = WARRANTY_REPLACEMENT_USD_PER_MWH * max(rated_mwh, 0.001)
    denom = max(warranty_cycles, 1) * max(rated_mwh, 0.001) * 2.0
    return (replacement_value / denom) * _deg_multiplier(soh_pct)


def _window_active(obligation: ExtractedObligation, current_hour: int) -> bool:
    return any(
        w.start_hour <= current_hour < w.end_hour for w in obligation.delivery_windows
    )


class HeuristicOptimizer(DispatchOptimizer):
    """Rule-based, fully-explainable dispatch optimizer."""

    async def optimize(
        self,
        fleet_state: dict[str, Any],
        current_lmp: float,
        obligations: Sequence[ExtractedObligation],
        current_hour: int,
    ) -> FleetDispatchPlan:
        assets = fleet_state.get("assets", {})
        # Stable, SOH-ranked asset list (healthiest first).
        ranked = sorted(
            assets.items(), key=lambda kv: kv[1].get("soh_pct", 100.0), reverse=True
        )
        least_healthy_id = ranked[-1][0] if ranked else "n/a"

        # --- Step 1: obligation reserve (prefer healthiest assets) -----------
        active_obligations = [o for o in obligations if _window_active(o, current_hour)]
        reserve_total = sum(o.committed_mw for o in active_obligations)
        available = {aid: self._available_mw(a) for aid, a in assets.items()}
        fleet_available = sum(available.values())
        reserve_alloc = self._allocate_reserve(ranked, available, reserve_total)

        obligation_status = self._build_obligation_status(
            obligations, active_obligations, current_hour, fleet_available
        )

        # --- Step 2: price signal -------------------------------------------
        if current_lmp > DISCHARGE_LMP:
            action = "DISCHARGE"
        elif current_lmp < CHARGE_LMP:
            action = "CHARGE"
        else:
            action = "HOLD"

        # --- Steps 3-5: per-asset allocation, costing & reasoning -----------
        decisions: list[DispatchDecision] = []
        for aid, a in assets.items():
            decisions.append(
                self._decide_asset(
                    aid,
                    a,
                    action,
                    current_lmp,
                    current_hour,
                    reserve_alloc.get(aid, 0.0),
                    least_healthy_id,
                    assets,
                )
            )

        interval_start = datetime.now(timezone.utc).isoformat()
        return FleetDispatchPlan(
            interval_start=interval_start,
            decisions=decisions,
            total_revenue_expected_usd=round(
                sum(d.revenue_expected_usd for d in decisions), 2
            ),
            total_constraint_cost_usd=round(
                sum(d.constraint_cost_usd for d in decisions), 2
            ),
            obligations_status=obligation_status,
            recommended_by="heuristic",
        )

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _is_generation(asset: dict[str, Any]) -> bool:
        return asset.get("asset_type") in ("Solar", "Wind")

    @classmethod
    def _available_mw(cls, asset: dict[str, Any]) -> float:
        """Dispatchable MW for this interval.

        Renewables are must-take: their availability is whatever they are
        generating right now (no SOC, no charging). Storage is rated power,
        gated by the SOC floor and thermal derate.
        """
        if cls._is_generation(asset):
            return max(0.0, float(asset.get("power_mw", 0.0)))
        rated_mw = float(asset.get("rated_mw", 10.0))
        if float(asset.get("soc_pct", 50.0)) <= SOC_FLOOR_PCT:
            return 0.0
        if float(asset.get("temperature_c", 25.0)) > THERMAL_THRESHOLD_C:
            return rated_mw * THERMAL_DERATE
        return rated_mw

    @staticmethod
    def _allocate_reserve(
        ranked: list[tuple[str, dict[str, Any]]],
        available: dict[str, float],
        reserve_total: float,
    ) -> dict[str, float]:
        """Assign obligation reserve to the healthiest assets first."""
        alloc: dict[str, float] = {}
        remaining = reserve_total
        for aid, _ in ranked:
            if remaining <= 0:
                break
            take = min(available.get(aid, 0.0), remaining)
            if take > 0:
                alloc[aid] = take
                remaining -= take
        return alloc

    def _build_obligation_status(
        self,
        obligations: Sequence[ExtractedObligation],
        active: list[ExtractedObligation],
        current_hour: int,
        fleet_available: float,
    ) -> list[ObligationStatus]:
        statuses: list[ObligationStatus] = []
        for i, obl in enumerate(obligations):
            obligation_id = f"{obl.obligation_type}-{i}"
            if obl not in active:
                statuses.append(
                    ObligationStatus(
                        obligation_id=obligation_id,
                        obligation_type=obl.obligation_type,
                        committed_mw=obl.committed_mw,
                        currently_covered_mw=0.0,
                        status="COVERED",
                        risk_reason=f"Not in a delivery window at hour {current_hour}",
                    )
                )
                continue

            covered = min(fleet_available, obl.committed_mw)
            buffer = (
                (fleet_available - obl.committed_mw) / obl.committed_mw
                if obl.committed_mw > 0
                else 1.0
            )
            if fleet_available < obl.committed_mw:
                status: ObligationStatus = ObligationStatus(
                    obligation_id, obl.obligation_type, obl.committed_mw, covered,
                    "BREACHED",
                    f"Fleet can supply only {fleet_available:.1f} MW of "
                    f"{obl.committed_mw:.1f} MW committed",
                )
            elif buffer < AT_RISK_BUFFER:
                status = ObligationStatus(
                    obligation_id, obl.obligation_type, obl.committed_mw, covered,
                    "AT_RISK",
                    f"Only {buffer * 100:.0f}% headroom above the "
                    f"{obl.committed_mw:.1f} MW commitment",
                )
            else:
                status = ObligationStatus(
                    obligation_id, obl.obligation_type, obl.committed_mw, covered,
                    "COVERED", None,
                )
            statuses.append(status)
        return statuses

    def _decide_asset(
        self,
        aid: str,
        asset: dict[str, Any],
        action: str,
        current_lmp: float,
        current_hour: int,
        reserved_mw: float,
        least_healthy_id: str,
        all_assets: dict[str, Any],
    ) -> DispatchDecision:
        # Renewables are must-take generation, not storage — handle separately.
        if self._is_generation(asset):
            return self._generation_decision(aid, asset, current_lmp)

        rated_mw = float(asset.get("rated_mw", 10.0))
        rated_mwh = float(asset.get("rated_mwh", rated_mw * 4.0))
        soh_pct = float(asset.get("soh_pct", 100.0))
        soc_pct = float(asset.get("soc_pct", 50.0))
        temp_c = float(asset.get("temperature_c", 25.0))
        warranty_cycles = int(asset.get("warranty_cycles", 6000))
        soh_frac = soh_pct / 100.0
        available = self._available_mw(asset)

        if action == "CHARGE":
            return self._charge_decision(
                aid, action, current_lmp, available, soh_frac
            )
        if action == "HOLD":
            return DispatchDecision(
                asset_id=aid,
                recommended_mw=0.0,
                reasoning=(
                    f"Holding at ${current_lmp:.0f}/MWh — within the "
                    f"${CHARGE_LMP:.0f}-${DISCHARGE_LMP:.0f}/MWh no-arbitrage band"
                ),
                binding_constraint=None,
                constraint_cost_usd=0.0,
                unconstrained_mw=0.0,
                revenue_expected_usd=0.0,
            )

        # --- DISCHARGE ------------------------------------------------------
        unconstrained_mw = rated_mw
        arbitrage_capacity = max(0.0, available - reserved_mw)
        recommended_mw = round(arbitrage_capacity * soh_frac, 2)

        # Constraint costs (cost of honoring each active constraint).
        costs: dict[str, float] = {}
        if soc_pct <= SOC_FLOOR_PCT:
            costs["SOC_FLOOR"] = round(rated_mw * current_lmp * INTERVAL_HOURS, 2)
        if temp_c > THERMAL_THRESHOLD_C:
            derated = rated_mw * THERMAL_DERATE
            costs["THERMAL_LIMIT"] = round(
                (rated_mw - derated) * current_lmp * INTERVAL_HOURS, 2
            )
        if reserved_mw > 0:
            costs["CAPACITY_OBLIGATION"] = round(
                reserved_mw * (current_lmp - NEXT_BEST_REVENUE), 2
            )
        spared_mw = arbitrage_capacity * (1.0 - soh_frac)
        if spared_mw > 0:
            deg_per_mwh = degradation_cost_per_mwh(rated_mwh, warranty_cycles, soh_pct)
            costs["DEGRADATION_COST"] = round(
                spared_mw * current_lmp * INTERVAL_HOURS + spared_mw * deg_per_mwh, 2
            )

        binding_constraint, constraint_cost = self._pick_binding(costs)
        reasoning = self._discharge_reasoning(
            aid, asset, binding_constraint, recommended_mw, reserved_mw,
            current_lmp, current_hour, constraint_cost, temp_c, soh_pct,
            least_healthy_id, all_assets,
        )
        return DispatchDecision(
            asset_id=aid,
            recommended_mw=recommended_mw,
            reasoning=reasoning,
            binding_constraint=binding_constraint,  # type: ignore[arg-type]
            constraint_cost_usd=constraint_cost,
            unconstrained_mw=round(unconstrained_mw, 2),
            revenue_expected_usd=round(recommended_mw * current_lmp * INTERVAL_HOURS, 2),
        )

    @staticmethod
    def _generation_decision(
        aid: str, asset: dict[str, Any], current_lmp: float
    ) -> DispatchDecision:
        """Must-take renewable: export current generation; never charge or curtail."""
        output = max(0.0, float(asset.get("power_mw", 0.0)))
        rated = float(asset.get("rated_mw", output) or output)
        atype = str(asset.get("asset_type", "renewable")).lower()
        cf = (output / rated * 100.0) if rated > 0 else 0.0
        return DispatchDecision(
            asset_id=aid,
            recommended_mw=round(output, 2),
            reasoning=(
                f"Exporting {output:.1f} MW of must-take {atype} generation at "
                f"${current_lmp:.0f}/MWh ({cf:.0f}% capacity factor)"
            ),
            binding_constraint=None,
            constraint_cost_usd=0.0,
            unconstrained_mw=round(rated, 2),
            revenue_expected_usd=round(output * current_lmp * INTERVAL_HOURS, 2),
        )

    @staticmethod
    def _charge_decision(
        aid: str, action: str, current_lmp: float, available: float, soh_frac: float
    ) -> DispatchDecision:
        # Most-degraded assets charge hardest (cheap cycles where SOH matters less).
        charge_weight = min(1.0, max(0.3, 1.3 - soh_frac))
        recommended_mw = round(-available * charge_weight, 2)
        return DispatchDecision(
            asset_id=aid,
            recommended_mw=recommended_mw,
            reasoning=(
                f"Charging {abs(recommended_mw):.1f} MW at ${current_lmp:.0f}/MWh "
                f"(below ${CHARGE_LMP:.0f} threshold) — buying cheap energy for later discharge"
            ),
            binding_constraint=None,
            constraint_cost_usd=0.0,
            unconstrained_mw=round(-available, 2),
            revenue_expected_usd=round(recommended_mw * current_lmp * INTERVAL_HOURS, 2),
        )

    @staticmethod
    def _pick_binding(costs: dict[str, float]) -> tuple[str | None, float]:
        if not costs:
            return None, 0.0
        binding = max(costs, key=lambda k: costs[k])
        return binding, costs[binding]

    @staticmethod
    def _discharge_reasoning(
        aid: str,
        asset: dict[str, Any],
        binding: str | None,
        recommended_mw: float,
        reserved_mw: float,
        current_lmp: float,
        current_hour: int,
        constraint_cost: float,
        temp_c: float,
        soh_pct: float,
        least_healthy_id: str,
        all_assets: dict[str, Any],
    ) -> str:
        if binding == "CAPACITY_OBLIGATION":
            revenue = reserved_mw * current_lmp * INTERVAL_HOURS
            return (
                f"Holding {reserved_mw:.1f} MW for capacity obligation at "
                f"{current_hour}:00 — deploying remainder costs ${constraint_cost:.0f} "
                f"in penalty exposure vs ${revenue:.0f} gained"
            )
        if binding == "THERMAL_LIMIT":
            return (
                f"Derated to {recommended_mw:.1f} MW — {aid} temperature "
                f"{temp_c:.0f}°C exceeds threshold"
            )
        if binding == "SOC_FLOOR":
            return (
                f"Holding {aid} at {recommended_mw:.1f} MW — SOC at "
                f"{float(asset.get('soc_pct', 0.0)):.0f}% is at the {SOC_FLOOR_PCT:.0f}% floor"
            )
        other_soh = float(all_assets.get(least_healthy_id, {}).get("soh_pct", soh_pct))
        return (
            f"Discharging {recommended_mw:.1f} MW at ${current_lmp:.0f}/MWh — routing to "
            f"{aid} (SOH {soh_pct:.0f}%) to spare {least_healthy_id} (SOH {other_soh:.0f}%)"
        )


def detect_spike(
    current_lmp: float,
    prev_lmp: float,
    threshold: float = 300.0,
    available_mw: float = 0.0,
    upcoming_obligation_mw: float = 0.0,
) -> SpikeAlert | None:
    """Detect a price spike worth interrupting the 5-minute loop for.

    Fires when the price is both absolutely high (> ``threshold``) and a sharp
    jump (> 150% of the previous tick).
    """
    if current_lmp > threshold and current_lmp > prev_lmp * 1.5:
        pct_change = ((current_lmp - prev_lmp) / prev_lmp * 100.0) if prev_lmp else 0.0
        additional_revenue = available_mw * (current_lmp - prev_lmp) * INTERVAL_HOURS
        return SpikeAlert(
            lmp=round(current_lmp, 2),
            prev_lmp=round(prev_lmp, 2),
            pct_change=round(pct_change, 1),
            recommended_action="DISCHARGE_FULL",
            additional_revenue_usd=round(additional_revenue, 2),
            obligation_risk=upcoming_obligation_mw > 0,
        )
    return None
