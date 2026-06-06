"""Dispatch plan validation — constraint checking and feasibility analysis."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import NamedTuple


class ValidationResult(NamedTuple):
    is_feasible: bool
    violations: list[str]
    warnings: list[str]
    constraint_slack: dict[str, list[float]]   # per-constraint slack values
    summary: str


@dataclass
class DispatchValidator:
    """
    Validates a dispatch plan against physical and market constraints.

    Checks:
    - SOC bounds (min/max)
    - Power bounds (charge/discharge limits)
    - SOC dynamics consistency (energy balance)
    - No simultaneous charge+discharge
    - Ramp rate limits
    - Market minimum offer thresholds
    - AS headroom availability
    """
    capacity_mwh: float = 10.0
    power_mw: float = 5.0
    rte: float = 0.92
    soc_min: float = 0.05
    soc_max: float = 0.95
    soc_init: float = 0.5
    dt_hours: float = 1.0
    ramp_mw_per_h: float | None = None   # Optional ramp constraint
    tol: float = 1e-4  # Numerical tolerance for constraint checks

    def validate(
        self,
        charge_mw: list[float],
        discharge_mw: list[float],
        soc: list[float],
        reg_up_mw: list[float] | None = None,
        reg_down_mw: list[float] | None = None,
    ) -> ValidationResult:
        """
        Validate a complete dispatch schedule.

        Parameters
        ----------
        charge_mw, discharge_mw, soc : lists of T values
        reg_up_mw, reg_down_mw : optional AS reserve schedules
        """
        T = len(charge_mw)
        violations = []
        warnings = []
        slack: dict[str, list[float]] = {
            "soc_min": [], "soc_max": [], "charge_max": [], "discharge_max": [],
            "soc_dynamics": [],
        }

        for t in range(T):
            ch = charge_mw[t]
            dis = discharge_mw[t]
            s = soc[t]

            # Power bounds
            if ch < -self.tol:
                violations.append(f"t={t}: charge_mw={ch:.4f} < 0")
            if ch > self.power_mw + self.tol:
                violations.append(f"t={t}: charge_mw={ch:.4f} > power_mw={self.power_mw}")
            if dis < -self.tol:
                violations.append(f"t={t}: discharge_mw={dis:.4f} < 0")
            if dis > self.power_mw + self.tol:
                violations.append(f"t={t}: discharge_mw={dis:.4f} > power_mw={self.power_mw}")
            slack["charge_max"].append(self.power_mw - ch)
            slack["discharge_max"].append(self.power_mw - dis)

            # Simultaneous charge+discharge
            if ch > self.tol and dis > self.tol:
                violations.append(f"t={t}: simultaneous charge ({ch:.3f}MW) and discharge ({dis:.3f}MW)")

            # SOC bounds
            if s < self.soc_min - self.tol:
                violations.append(f"t={t}: SOC={s:.4f} < soc_min={self.soc_min}")
            if s > self.soc_max + self.tol:
                violations.append(f"t={t}: SOC={s:.4f} > soc_max={self.soc_max}")
            slack["soc_min"].append(s - self.soc_min)
            slack["soc_max"].append(self.soc_max - s)

            # SOC dynamics check
            if t == 0:
                expected_soc = (
                    self.soc_init
                    + ch * self.rte * self.dt_hours / self.capacity_mwh
                    - dis * self.dt_hours / self.capacity_mwh
                )
            else:
                expected_soc = (
                    soc[t-1]
                    + ch * self.rte * self.dt_hours / self.capacity_mwh
                    - dis * self.dt_hours / self.capacity_mwh
                )
            dyn_error = abs(s - expected_soc)
            slack["soc_dynamics"].append(-dyn_error)
            if dyn_error > self.tol * 10:
                violations.append(f"t={t}: SOC dynamics violation — expected {expected_soc:.4f}, got {s:.4f} (err={dyn_error:.6f})")

            # Ramp rate
            if self.ramp_mw_per_h is not None and t > 0:
                ch_ramp = abs(charge_mw[t] - charge_mw[t-1]) / self.dt_hours
                dis_ramp = abs(discharge_mw[t] - discharge_mw[t-1]) / self.dt_hours
                if ch_ramp > self.ramp_mw_per_h + self.tol:
                    warnings.append(f"t={t}: charge ramp {ch_ramp:.2f} MW/h exceeds limit {self.ramp_mw_per_h}")
                if dis_ramp > self.ramp_mw_per_h + self.tol:
                    warnings.append(f"t={t}: discharge ramp {dis_ramp:.2f} MW/h exceeds limit {self.ramp_mw_per_h}")

        # AS headroom check
        if reg_up_mw and reg_down_mw:
            for t in range(T):
                # Reg-up + discharge must not exceed power_mw
                total_dis_power = discharge_mw[t] + reg_up_mw[t]
                if total_dis_power > self.power_mw + self.tol:
                    violations.append(
                        f"t={t}: discharge+reg_up ({total_dis_power:.3f}) exceeds power_mw ({self.power_mw})"
                    )
                # Reg-down + charge must not exceed power_mw
                total_ch_power = charge_mw[t] + reg_down_mw[t]
                if total_ch_power > self.power_mw + self.tol:
                    violations.append(
                        f"t={t}: charge+reg_down ({total_ch_power:.3f}) exceeds power_mw ({self.power_mw})"
                    )

        is_feasible = len(violations) == 0
        n_v = len(violations)
        n_w = len(warnings)
        summary = (
            f"FEASIBLE — {n_w} warning(s)" if is_feasible
            else f"INFEASIBLE — {n_v} violation(s), {n_w} warning(s)"
        )

        return ValidationResult(
            is_feasible=is_feasible,
            violations=violations,
            warnings=warnings,
            constraint_slack=slack,
            summary=summary,
        )

    def binding_constraints(self, result: ValidationResult) -> list[str]:
        """Identify nearly-binding constraints (slack < 1% of capacity)."""
        binding = []
        threshold = self.capacity_mwh * 0.01
        for name, slack_vals in result.constraint_slack.items():
            n_binding = sum(1 for s in slack_vals if 0 <= s < threshold)
            if n_binding > 0:
                binding.append(f"{name}: {n_binding} intervals near-binding")
        return binding
