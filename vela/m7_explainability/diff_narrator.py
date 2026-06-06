"""Diff narrator: explains differences between planned vs actual dispatch."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple


class DispatchDiff(NamedTuple):
    interval: int
    timestamp: datetime | None
    planned_charge_mw: float
    actual_charge_mw: float
    planned_discharge_mw: float
    actual_discharge_mw: float
    charge_deviation_mw: float
    discharge_deviation_mw: float
    revenue_impact: float     # $ — positive = actual better, negative = actual worse
    lmp: float
    reason_category: str      # "constraint", "forecast_error", "curtailment", "manual", "none"
    narrative: str


@dataclass
class DispatchDiffNarrator:
    """
    Generates human-readable narratives explaining planned vs. actual dispatch differences.

    Common deviation causes:
    - SOC constraint violations (actual SOC differed from forecast)
    - LMP forecast errors (actual LMP triggered different actions)
    - Grid curtailment (ISO instructed asset to deviate)
    - Manual override by operator
    - Equipment limits (temperature, degradation)
    """
    deviation_threshold_mw: float = 0.5     # Deviations below this are ignored
    revenue_threshold: float = 10.0         # $ — deviations below this are minor

    def narrate(
        self,
        planned_charge: list[float],
        planned_discharge: list[float],
        actual_charge: list[float],
        actual_discharge: list[float],
        actual_lmp: list[float],
        planned_lmp: list[float] | None = None,
        actual_soc: list[float] | None = None,
        planned_soc: list[float] | None = None,
        timestamps: list[datetime] | None = None,
    ) -> list[DispatchDiff]:
        """
        Compare planned and actual dispatch schedules.

        Returns a list of DispatchDiff objects for intervals with significant deviations.
        """
        T = len(planned_charge)
        diffs = []

        for t in range(T):
            ch_dev = actual_charge[t] - planned_charge[t]
            dis_dev = actual_discharge[t] - planned_discharge[t]
            lmp = actual_lmp[t]
            ts = timestamps[t] if timestamps else None

            # Revenue impact = (actual - planned) net energy * actual LMP
            net_planned = planned_discharge[t] - planned_charge[t]
            net_actual = actual_discharge[t] - actual_charge[t]
            rev_impact = (net_actual - net_planned) * lmp

            total_dev = abs(ch_dev) + abs(dis_dev)
            if total_dev < self.deviation_threshold_mw and abs(rev_impact) < self.revenue_threshold:
                continue

            # Classify deviation cause
            reason, narrative = self._classify_deviation(
                t=t,
                ch_dev=ch_dev,
                dis_dev=dis_dev,
                lmp=lmp,
                planned_lmp=planned_lmp[t] if planned_lmp else None,
                actual_soc=actual_soc[t] if actual_soc else None,
                planned_soc=planned_soc[t] if planned_soc else None,
                rev_impact=rev_impact,
            )

            diffs.append(DispatchDiff(
                interval=t,
                timestamp=ts,
                planned_charge_mw=planned_charge[t],
                actual_charge_mw=actual_charge[t],
                planned_discharge_mw=planned_discharge[t],
                actual_discharge_mw=actual_discharge[t],
                charge_deviation_mw=ch_dev,
                discharge_deviation_mw=dis_dev,
                revenue_impact=rev_impact,
                lmp=lmp,
                reason_category=reason,
                narrative=narrative,
            ))

        return diffs

    def _classify_deviation(
        self,
        t: int,
        ch_dev: float,
        dis_dev: float,
        lmp: float,
        planned_lmp: float | None,
        actual_soc: float | None,
        planned_soc: float | None,
        rev_impact: float,
    ) -> tuple[str, str]:
        """Classify the cause of a dispatch deviation and generate narrative."""

        # SOC-driven deviation
        if actual_soc is not None and planned_soc is not None:
            soc_diff = actual_soc - planned_soc
            if abs(soc_diff) > 0.05:
                if soc_diff < -0.05 and dis_dev < -self.deviation_threshold_mw:
                    return (
                        "constraint",
                        f"Hour {t}: Discharge reduced by {abs(dis_dev):.2f} MW because actual SOC "
                        f"({actual_soc:.1%}) was {abs(soc_diff):.1%} lower than planned ({planned_soc:.1%}). "
                        f"Revenue impact: ${rev_impact:+.2f}."
                    )
                elif soc_diff > 0.05 and ch_dev < -self.deviation_threshold_mw:
                    return (
                        "constraint",
                        f"Hour {t}: Charging reduced by {abs(ch_dev):.2f} MW because actual SOC "
                        f"({actual_soc:.1%}) was higher than planned ({planned_soc:.1%}). "
                        f"Revenue impact: ${rev_impact:+.2f}."
                    )

        # Forecast error driven deviation
        if planned_lmp is not None:
            lmp_error = lmp - planned_lmp
            if abs(lmp_error) > 10.0:
                if lmp_error > 10 and dis_dev > self.deviation_threshold_mw:
                    return (
                        "forecast_error",
                        f"Hour {t}: Actual LMP ${lmp:.1f}/MWh was ${lmp_error:+.1f} above forecast "
                        f"${planned_lmp:.1f}/MWh. Discharged {dis_dev:+.2f} MW more than planned. "
                        f"Revenue benefit: ${rev_impact:+.2f}."
                    )
                elif lmp_error < -10 and ch_dev > self.deviation_threshold_mw:
                    return (
                        "forecast_error",
                        f"Hour {t}: Actual LMP ${lmp:.1f}/MWh was ${abs(lmp_error):.1f} below forecast "
                        f"${planned_lmp:.1f}/MWh. Charged {ch_dev:+.2f} MW more than planned. "
                        f"Revenue impact: ${rev_impact:+.2f}."
                    )

        # Generic deviations
        if dis_dev < -self.deviation_threshold_mw:
            return (
                "constraint",
                f"Hour {t}: Discharge was {abs(dis_dev):.2f} MW below plan. "
                f"LMP=${lmp:.1f}/MWh. Revenue impact: ${rev_impact:+.2f}.",
            )
        elif ch_dev > self.deviation_threshold_mw:
            return (
                "curtailment",
                f"Hour {t}: Charged {ch_dev:.2f} MW more than planned at LMP=${lmp:.1f}/MWh. "
                f"Revenue impact: ${rev_impact:+.2f}.",
            )

        return (
            "none",
            f"Hour {t}: Minor deviation — charge {ch_dev:+.2f} MW, discharge {dis_dev:+.2f} MW. "
            f"Revenue impact: ${rev_impact:+.2f}.",
        )

    def summary_report(self, diffs: list[DispatchDiff]) -> dict:
        """Generate a summary of all deviations."""
        if not diffs:
            return {"n_deviations": 0, "total_revenue_impact": 0.0, "categories": {}}

        total_rev = sum(d.revenue_impact for d in diffs)
        by_category: dict[str, int] = {}
        for d in diffs:
            by_category[d.reason_category] = by_category.get(d.reason_category, 0) + 1

        worst = min(diffs, key=lambda d: d.revenue_impact)
        best = max(diffs, key=lambda d: d.revenue_impact)

        return {
            "n_deviations": len(diffs),
            "total_revenue_impact": total_rev,
            "categories": by_category,
            "worst_interval": worst.interval,
            "worst_revenue_impact": worst.revenue_impact,
            "best_interval": best.interval,
            "best_revenue_impact": best.revenue_impact,
        }
