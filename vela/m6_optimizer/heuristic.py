"""Heuristic dispatch for fast real-time control with sub-millisecond response."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple


class HeuristicAction(NamedTuple):
    charge_mw: float
    discharge_mw: float
    soc_pct: float
    strategy: str
    expected_revenue_h: float  # $/h


@dataclass
class PeakShavingHeuristic:
    """
    Peak shaving dispatch heuristic.

    Charges during low-demand hours and discharges to shave peaks,
    reducing demand charges for C&I customers.

    Demand charge structure:
    - Monthly peak demand (kW) × demand_rate ($/kW-month)
    - Reducing the monthly peak can save thousands $/month
    """
    capacity_mwh: float = 10.0
    power_mw: float = 5.0
    rte: float = 0.92
    soc_min: float = 0.05
    soc_max: float = 0.95
    dt_hours: float = 1.0
    peak_shave_target_mw: float = 8.0   # Target facility peak (MW)
    demand_rate_per_mw: float = 150.0   # $/MW-month
    _soc: float = field(default=0.5, init=False, repr=False)
    _monthly_peak: float = field(default=0.0, init=False, repr=False)

    def reset(self, soc: float = 0.5) -> None:
        self._soc = float(np.clip(soc, self.soc_min, self.soc_max))
        self._monthly_peak = 0.0

    def act(self, facility_load_mw: float, grid_price: float = 35.0) -> HeuristicAction:
        """
        Execute peak shaving action.

        If facility load exceeds target, discharge battery.
        If load is low (< 60% of target), charge battery.
        """
        excess = facility_load_mw - self.peak_shave_target_mw
        self._monthly_peak = max(self._monthly_peak, facility_load_mw)

        if excess > 0.1 and self._soc > self.soc_min + 0.02:
            # Shave the peak
            dis = min(self.power_mw, excess,
                      (self._soc - self.soc_min) * self.capacity_mwh / self.dt_hours)
            self._soc -= dis * self.dt_hours / self.capacity_mwh
            return HeuristicAction(
                charge_mw=0.0, discharge_mw=dis, soc_pct=self._soc,
                strategy="peak_shave",
                expected_revenue_h=dis * self.demand_rate_per_mw / (30 * 24),
            )
        elif facility_load_mw < self.peak_shave_target_mw * 0.6 and self._soc < self.soc_max - 0.02:
            ch = min(self.power_mw, (self.soc_max - self._soc) * self.capacity_mwh / self.dt_hours)
            self._soc += ch * self.rte * self.dt_hours / self.capacity_mwh
            return HeuristicAction(
                charge_mw=ch, discharge_mw=0.0, soc_pct=self._soc,
                strategy="opportunistic_charge",
                expected_revenue_h=-ch * grid_price * self.dt_hours,
            )
        return HeuristicAction(0.0, 0.0, self._soc, "idle", 0.0)


@dataclass
class FrequencyRegulationHeuristic:
    """
    Fast-responding frequency regulation dispatch.

    Responds to AGC (Automatic Generation Control) signals.
    Battery acts as a virtual governor.
    """
    capacity_mwh: float = 5.0
    power_mw: float = 5.0    # 1:1 E/P ratio for reg
    rte: float = 0.92
    soc_min: float = 0.20    # Higher minimum for reg — need headroom both ways
    soc_max: float = 0.80    # Lower max for reg
    soc_target: float = 0.50
    dt_hours: float = 1 / 60  # 1-minute intervals for AGC
    reg_capacity_mw: float = 2.0  # Committed regulation capacity
    _soc: float = field(default=0.5, init=False, repr=False)

    def reset(self, soc: float = 0.5) -> None:
        self._soc = float(np.clip(soc, self.soc_min, self.soc_max))

    def respond_to_agc(self, agc_signal: float) -> HeuristicAction:
        """
        Respond to AGC signal.

        agc_signal: -1 to +1 (normalized)
            +1 = full reg-up (discharge)
            -1 = full reg-down (charge)
        """
        commanded_mw = agc_signal * self.reg_capacity_mw

        if commanded_mw > 0:  # Discharge (reg up)
            actual = min(commanded_mw, (self._soc - self.soc_min) * self.capacity_mwh / self.dt_hours)
            actual = max(0.0, actual)
            self._soc -= actual * self.dt_hours / self.capacity_mwh
            return HeuristicAction(0.0, actual, self._soc, "reg_up", actual * 15.0 * self.dt_hours)
        else:  # Charge (reg down)
            actual = min(abs(commanded_mw), (self.soc_max - self._soc) * self.capacity_mwh / self.dt_hours)
            actual = max(0.0, actual)
            self._soc += actual * self.rte * self.dt_hours / self.capacity_mwh
            return HeuristicAction(actual, 0.0, self._soc, "reg_down", actual * 10.0 * self.dt_hours)

    def soc_restoration_action(self) -> HeuristicAction:
        """
        Restore SOC toward target between AGC signals.

        Called during intervals when no AGC signal is received.
        """
        deviation = self.soc_target - self._soc
        if deviation > 0.05 and self._soc < self.soc_max - 0.02:
            ch = min(self.power_mw * 0.3, deviation * self.capacity_mwh / self.dt_hours)
            self._soc += ch * self.rte * self.dt_hours / self.capacity_mwh
            return HeuristicAction(ch, 0.0, self._soc, "soc_restore_charge", 0.0)
        elif deviation < -0.05 and self._soc > self.soc_min + 0.02:
            dis = min(self.power_mw * 0.3, abs(deviation) * self.capacity_mwh / self.dt_hours)
            self._soc -= dis * self.dt_hours / self.capacity_mwh
            return HeuristicAction(0.0, dis, self._soc, "soc_restore_discharge", 0.0)
        return HeuristicAction(0.0, 0.0, self._soc, "idle", 0.0)


@dataclass
class TimeOfUseHeuristic:
    """
    Time-of-Use (TOU) rate optimization heuristic.

    Charges during off-peak rate periods, discharges during on-peak.
    Common for behind-the-meter (BTM) applications.
    """
    capacity_mwh: float = 10.0
    power_mw: float = 5.0
    rte: float = 0.92
    soc_min: float = 0.05
    soc_max: float = 0.95
    dt_hours: float = 0.25  # 15-min intervals
    # TOU schedule: hour_of_day -> rate $/kWh (converted to $/MWh)
    tou_schedule: dict[int, float] = field(default_factory=lambda: {
        h: 0.08 * 1000 if 9 <= h <= 20 else 0.05 * 1000  # $80/MWh on-peak, $50/MWh off-peak
        for h in range(24)
    })
    _soc: float = field(default=0.5, init=False, repr=False)

    def reset(self, soc: float = 0.5) -> None:
        self._soc = float(np.clip(soc, self.soc_min, self.soc_max))

    def is_on_peak(self, hour: int) -> bool:
        rates = list(self.tou_schedule.values())
        median_rate = float(np.median(rates))
        return self.tou_schedule.get(hour, median_rate) >= median_rate

    def act(self, hour: int) -> HeuristicAction:
        rate = self.tou_schedule.get(hour, 60.0)
        on_peak = self.is_on_peak(hour)

        if on_peak and self._soc > self.soc_min + 0.05:
            dis = min(self.power_mw, (self._soc - self.soc_min) * self.capacity_mwh / self.dt_hours)
            self._soc -= dis * self.dt_hours / self.capacity_mwh
            return HeuristicAction(0.0, dis, self._soc, "tou_discharge", dis * rate * self.dt_hours)
        elif not on_peak and self._soc < self.soc_max - 0.05:
            ch = min(self.power_mw, (self.soc_max - self._soc) * self.capacity_mwh / self.dt_hours)
            self._soc += ch * self.rte * self.dt_hours / self.capacity_mwh
            return HeuristicAction(ch, 0.0, self._soc, "tou_charge", -ch * rate * self.dt_hours)
        return HeuristicAction(0.0, 0.0, self._soc, "idle", 0.0)
