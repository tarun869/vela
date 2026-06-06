"""
Battery degradation simulation model.

Models calendar aging, cycle aging, and temperature-accelerated
degradation for lithium-ion battery systems (LFP, NMC, NCA chemistries).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import numpy as np


class BatteryChemistry(str, Enum):
    LFP = "lfp"        # LiFePO4 — best cycle life
    NMC = "nmc"        # LiNiMnCoO2 — high energy density
    NCA = "nca"        # LiNiCoAlO2 — high performance
    LTO = "lto"        # Li4Ti5O12 — extreme cycle life


@dataclass
class DegradationParams:
    """Chemistry-specific degradation model parameters."""
    chemistry: BatteryChemistry
    # Calendar aging: capacity_loss = k_cal * sqrt(time_years) * exp(-Ea/(R*T))
    k_cal: float                  # Calendar aging pre-factor
    e_act_cal_j_mol: float        # Activation energy (J/mol)
    # Cycle aging: capacity_loss = k_cyc * (Ah_throughput)^alpha
    k_cyc: float                  # Cycle aging pre-factor
    alpha_cyc: float = 0.5        # Ah throughput exponent
    # DoD stress: multiplier on cycle aging for deep discharges
    dod_factor_100pct: float = 1.5  # Factor at 100% DoD vs 50%
    # Temperature: Arrhenius acceleration
    t_ref_c: float = 25.0         # Reference temperature (°C)
    # End of life
    eol_capacity_pct: float = 80.0  # End of life at 80% capacity


# Typical parameters per chemistry (literature-based estimates)
CHEM_PARAMS: Dict[BatteryChemistry, DegradationParams] = {
    BatteryChemistry.LFP: DegradationParams(
        chemistry=BatteryChemistry.LFP,
        k_cal=0.0015, e_act_cal_j_mol=55000,
        k_cyc=0.00008, alpha_cyc=0.50,
        dod_factor_100pct=1.3, t_ref_c=25.0, eol_capacity_pct=80.0
    ),
    BatteryChemistry.NMC: DegradationParams(
        chemistry=BatteryChemistry.NMC,
        k_cal=0.0025, e_act_cal_j_mol=65000,
        k_cyc=0.00012, alpha_cyc=0.55,
        dod_factor_100pct=1.8, t_ref_c=25.0, eol_capacity_pct=80.0
    ),
    BatteryChemistry.NCA: DegradationParams(
        chemistry=BatteryChemistry.NCA,
        k_cal=0.0030, e_act_cal_j_mol=70000,
        k_cyc=0.00015, alpha_cyc=0.60,
        dod_factor_100pct=2.0, t_ref_c=25.0, eol_capacity_pct=80.0
    ),
    BatteryChemistry.LTO: DegradationParams(
        chemistry=BatteryChemistry.LTO,
        k_cal=0.0008, e_act_cal_j_mol=45000,
        k_cyc=0.00003, alpha_cyc=0.45,
        dod_factor_100pct=1.1, t_ref_c=25.0, eol_capacity_pct=80.0
    ),
}

R_GAS = 8.314  # J/(mol·K)


@dataclass
class DegradationState:
    time_years: float
    capacity_pct: float           # Remaining capacity (%)
    calendar_loss_pct: float
    cycle_loss_pct: float
    ah_throughput: float
    equivalent_cycles: float
    reached_eol: bool


class BatteryDegradationModel:
    """
    Physics-based battery degradation model.

    Computes capacity fade from:
      1. Calendar aging (sqrt(t) dependency, Arrhenius temperature)
      2. Cycle aging (Ah throughput, DoD weighting)
    """

    def __init__(
        self,
        chemistry: BatteryChemistry,
        capacity_kwh: float,
        t_ambient_c: float = 25.0,
    ) -> None:
        self.params = CHEM_PARAMS[chemistry]
        self.capacity_kwh = capacity_kwh
        self.t_ambient_c = t_ambient_c
        self._time_years = 0.0
        self._ah_throughput = 0.0
        self._calendar_loss = 0.0
        self._cycle_loss = 0.0

    @property
    def capacity_pct(self) -> float:
        return max(0.0, 100.0 - self._calendar_loss - self._cycle_loss)

    @property
    def remaining_capacity_kwh(self) -> float:
        return self.capacity_kwh * self.capacity_pct / 100.0

    def _arrhenius_factor(self, temp_c: float) -> float:
        """Temperature acceleration factor relative to reference temp."""
        t_k = temp_c + 273.15
        t_ref_k = self.params.t_ref_c + 273.15
        return math.exp(-self.params.e_act_cal_j_mol / R_GAS * (1/t_k - 1/t_ref_k))

    def _dod_stress(self, dod_fraction: float) -> float:
        """
        DoD stress multiplier for cycle aging.
        Linear interpolation: 1.0 at 50% DoD, dod_factor at 100% DoD.
        """
        base_dod = 0.5
        max_factor = self.params.dod_factor_100pct
        slope = (max_factor - 1.0) / (1.0 - base_dod)
        return max(1.0, 1.0 + slope * max(0, dod_fraction - base_dod))

    def step(
        self,
        dt_h: float,
        power_kw: float,
        dod_fraction: float = 0.5,
        temp_c: Optional[float] = None,
    ) -> DegradationState:
        """
        Advance degradation model by one time step.

        Args:
            dt_h: Time step (hours).
            power_kw: Average power during step (kW, positive = discharge).
            dod_fraction: Depth of discharge during this cycle (0–1).
            temp_c: Temperature (°C), uses ambient if None.

        Returns:
            Updated DegradationState.
        """
        temp = temp_c if temp_c is not None else self.t_ambient_c
        dt_years = dt_h / 8760.0
        self._time_years += dt_years

        # Ah throughput this step
        voltage_v = 800.0  # Nominal voltage
        ah_step = abs(power_kw) * dt_h * 1000.0 / voltage_v
        self._ah_throughput += ah_step

        # Calendar aging increment
        arr_factor = self._arrhenius_factor(temp)
        cal_loss_rate = self.params.k_cal * arr_factor
        # d(capacity) / d(sqrt(t)) = k_cal * arr
        # Cal loss grows as k * sqrt(t)
        cal_total = self.params.k_cal * arr_factor * math.sqrt(self._time_years) * 100.0
        self._calendar_loss = cal_total

        # Cycle aging (power law on Ah throughput)
        dod_mult = self._dod_stress(dod_fraction)
        cyc_total = (self.params.k_cyc * (self._ah_throughput ** self.params.alpha_cyc)
                     * dod_mult * 100.0)
        self._cycle_loss = cyc_total

        eq_cycles = self._ah_throughput / (2 * self.capacity_kwh * 1000 / voltage_v)
        eol = self.capacity_pct < self.params.eol_capacity_pct

        return DegradationState(
            time_years=self._time_years,
            capacity_pct=self.capacity_pct,
            calendar_loss_pct=self._calendar_loss,
            cycle_loss_pct=self._cycle_loss,
            ah_throughput=self._ah_throughput,
            equivalent_cycles=eq_cycles,
            reached_eol=eol,
        )

    def simulate_lifetime(
        self,
        power_profile_kw: List[float],
        dt_h: float = 1.0,
        temp_profile_c: Optional[List[float]] = None,
    ) -> Tuple[List[DegradationState], float]:
        """
        Simulate full battery lifetime until EOL.

        Returns:
            (states, years_to_eol)
        """
        states: List[DegradationState] = []
        n = len(power_profile_kw)
        temp_profile = temp_profile_c or [self.t_ambient_c] * n

        for i in range(n):
            state = self.step(
                dt_h=dt_h,
                power_kw=power_profile_kw[i],
                temp_c=temp_profile[i],
            )
            states.append(state)
            if state.reached_eol:
                break

        years_to_eol = states[-1].time_years if states and states[-1].reached_eol else None
        return states, years_to_eol or float("inf")

    def expected_lifetime_years(
        self,
        avg_cycles_per_year: float = 365.0,
        avg_dod: float = 0.8,
        avg_temp_c: float = 25.0,
    ) -> float:
        """
        Estimate expected calendar lifetime at given duty cycle.

        Returns years to EOL.
        """
        # Binary search for EOL
        lo, hi = 0.5, 30.0
        arr = self._arrhenius_factor(avg_temp_c)

        for _ in range(100):
            t = (lo + hi) / 2.0
            cal_loss = self.params.k_cal * arr * math.sqrt(t) * 100.0

            # Cycle aging: ah_throughput at t years
            voltage_v = 800.0
            ah_per_cycle = 2 * self.capacity_kwh * 1000 / voltage_v * avg_dod
            total_ah = avg_cycles_per_year * t * ah_per_cycle
            dod_mult = self._dod_stress(avg_dod)
            cyc_loss = self.params.k_cyc * (total_ah ** self.params.alpha_cyc) * dod_mult * 100.0

            capacity_pct = 100.0 - cal_loss - cyc_loss

            if capacity_pct > self.params.eol_capacity_pct:
                lo = t
            else:
                hi = t

        return (lo + hi) / 2.0
