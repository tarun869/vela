"""
Thermal comfort optimizer using the PMV (Predicted Mean Vote) model.

Implements ISO 7730 / ASHRAE 55 Predicted Mean Vote and Predicted
Percentage Dissatisfied (PPD) calculation, plus a comfort-constrained
HVAC optimization that minimizes energy while keeping PMV in bounds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class ThermalEnvironment:
    """Input parameters for the PMV model."""
    t_air: float             # Air temperature (°C)
    t_mrt: float             # Mean radiant temperature (°C)
    v_air: float             # Air velocity (m/s), >= 0
    rh_percent: float        # Relative humidity (%)
    met: float = 1.2         # Metabolic rate (met), 1.0=seated, 1.2=light work
    clo: float = 1.0         # Clothing insulation (clo), 1.0=typical office


@dataclass
class ComfortResult:
    pmv: float           # Predicted Mean Vote (-3 to +3)
    ppd: float           # Predicted Percentage Dissatisfied (%)
    t_operative: float   # Operative temperature (°C)
    sensation: str       # Text label


def _water_vapor_pressure(rh: float, t_air: float) -> float:
    """Antoine equation for saturation pressure, then apply RH."""
    p_sat = math.exp(16.6536 - 4030.18 / (t_air + 235.0))  # kPa
    return rh / 100.0 * p_sat * 1000.0  # Pa


def _clothing_surface_temp(t_cl_guess: float, t_air: float, t_mrt: float,
                            v_air: float, icl: float, m_w: float) -> float:
    """Iterate clothing surface temperature using heat balance (simplified Newton)."""
    for _ in range(150):
        if t_cl_guess > 36.0:
            f_cl = 1.05 + 0.1 * icl
        else:
            f_cl = 1.0 + 0.2 * icl

        hc = max(2.38 * abs(t_cl_guess - t_air) ** 0.25, 12.1 * math.sqrt(v_air))

        t_cl_new = (
            35.7
            - 0.028 * m_w
            - icl * (
                3.96e-8 * f_cl * ((t_cl_guess + 273.0) ** 4 - (t_mrt + 273.0) ** 4)
                + f_cl * hc * (t_cl_guess - t_air)
            )
        )
        if abs(t_cl_new - t_cl_guess) < 0.001:
            return t_cl_new
        t_cl_guess = t_cl_new
    return t_cl_guess


def pmv_ppd(env: ThermalEnvironment) -> ComfortResult:
    """
    Compute PMV and PPD per ISO 7730.

    PMV scale:
        -3 Cold, -2 Cool, -1 Slightly Cool,
         0 Neutral,
        +1 Slightly Warm, +2 Warm, +3 Hot
    """
    ta = env.t_air
    tr = env.t_mrt
    vel = max(env.v_air, 0.0)
    rh = env.rh_percent
    met = env.met
    clo = env.clo

    # Unit conversions
    icl = 0.155 * clo   # m^2·K/W
    m = met * 58.15     # W/m^2 metabolic rate
    w = 0.0             # External work (W/m^2) — assume zero
    m_w = m - w

    pa = _water_vapor_pressure(rh, ta)  # Pa

    # Clothing factor
    f_cl = 1.05 + 0.1 * icl if icl > 0.078 else 1.0 + 1.29 * icl

    # Clothing surface temperature (initial guess)
    t_cl = _clothing_surface_temp(
        t_cl_guess=(ta + tr) / 2.0 + 0.1,
        t_air=ta, t_mrt=tr, v_air=vel, icl=icl, m_w=m_w
    )

    hc = max(2.38 * abs(t_cl - ta) ** 0.25, 12.1 * math.sqrt(vel))

    # Heat losses
    hl1 = 3.05e-3 * (5733.0 - 6.99 * m_w - pa)          # Evap loss through skin
    hl2 = max(0.0, 0.42 * (m_w - 58.15))                  # Sweat evaporation
    hl3 = 1.7e-5 * m * (5867.0 - pa)                      # Latent respiration
    hl4 = 0.0014 * m * (34.0 - ta)                        # Sensible respiration
    hl5 = 3.96e-8 * f_cl * ((t_cl + 273.0) ** 4 - (tr + 273.0) ** 4)  # Radiation
    hl6 = f_cl * hc * (t_cl - ta)                         # Convection

    ts = 0.303 * math.exp(-0.036 * m) + 0.028
    pmv = ts * (m_w - hl1 - hl2 - hl3 - hl4 - hl5 - hl6)
    pmv = max(-3.0, min(3.0, pmv))

    ppd = 100.0 - 95.0 * math.exp(-0.03353 * pmv**4 - 0.2179 * pmv**2)
    t_operative = (ta + tr) / 2.0

    labels = {
        pmv <= -2.5: "Cold",
        -2.5 < pmv <= -1.5: "Cool",
        -1.5 < pmv <= -0.5: "Slightly Cool",
        -0.5 < pmv <= 0.5: "Neutral",
        0.5 < pmv <= 1.5: "Slightly Warm",
        1.5 < pmv <= 2.5: "Warm",
        pmv > 2.5: "Hot",
    }
    sensation = next((v for k, v in labels.items() if k), "Neutral")

    return ComfortResult(pmv=pmv, ppd=ppd, t_operative=t_operative, sensation=sensation)


class ComfortOptimizer:
    """
    Optimize HVAC setpoint to minimize energy while satisfying PMV constraints.

    Searches over a temperature range to find the setpoint with minimum
    HVAC load that keeps PMV within [pmv_min, pmv_max].
    """

    def __init__(
        self,
        pmv_min: float = -0.5,
        pmv_max: float = 0.5,
        t_min_c: float = 18.0,
        t_max_c: float = 28.0,
    ) -> None:
        self.pmv_min = pmv_min
        self.pmv_max = pmv_max
        self.t_min_c = t_min_c
        self.t_max_c = t_max_c

    def find_optimal_setpoint(
        self,
        t_outdoor: float,
        rh: float,
        t_mrt: Optional[float] = None,
        v_air: float = 0.15,
        met: float = 1.2,
        clo: float = 1.0,
        n_points: int = 100,
    ) -> Tuple[float, ComfortResult]:
        """
        Find the minimum-energy setpoint within comfort bounds.

        For heating: maximize setpoint (less heating needed).
        For cooling: minimize setpoint (less cooling needed).
        The optimal setpoint is the one closest to outdoor temperature
        while still satisfying PMV constraints.

        Returns:
            (optimal_setpoint_°C, ComfortResult at that setpoint)
        """
        temps = np.linspace(self.t_min_c, self.t_max_c, n_points)
        feasible: List[Tuple[float, ComfortResult]] = []

        for t in temps:
            t_mrt_val = t_mrt if t_mrt is not None else t + 1.0
            env = ThermalEnvironment(
                t_air=t, t_mrt=t_mrt_val, v_air=v_air,
                rh_percent=rh, met=met, clo=clo
            )
            result = pmv_ppd(env)
            if self.pmv_min <= result.pmv <= self.pmv_max:
                feasible.append((t, result))

        if not feasible:
            # No feasible setpoint — return neutral midpoint
            t_neutral = (self.t_min_c + self.t_max_c) / 2.0
            env = ThermalEnvironment(
                t_air=t_neutral, t_mrt=t_mrt or t_neutral + 1.0,
                v_air=v_air, rh_percent=rh, met=met, clo=clo
            )
            return t_neutral, pmv_ppd(env)

        # Pick the feasible setpoint closest to outdoor (minimizes HVAC delta-T)
        best = min(feasible, key=lambda x: abs(x[0] - t_outdoor))
        return best

    def adaptive_comfort_band(self, t_outdoor_running_mean: float) -> Tuple[float, float]:
        """
        ASHRAE 55 adaptive comfort model.
        Returns (t_lower_80_acceptability, t_upper_80_acceptability) in °C.
        """
        # Applicable for naturally ventilated buildings
        t_comf = 0.31 * t_outdoor_running_mean + 17.8
        return t_comf - 3.5, t_comf + 3.5

    def comfort_energy_tradeoff(
        self,
        t_outdoor_series: List[float],
        rh_series: List[float],
        baseline_setpoint: float = 22.0,
    ) -> Dict[str, List[float]]:
        """
        Evaluate comfort and energy delta vs baseline setpoint over a time series.

        Returns dict with 'pmv', 'ppd', 'optimal_setpoint', 'setpoint_delta'.
        """
        results: Dict[str, List[float]] = {
            "pmv": [], "ppd": [], "optimal_setpoint": [], "setpoint_delta": []
        }

        for t_out, rh in zip(t_outdoor_series, rh_series):
            t_opt, comfort = self.find_optimal_setpoint(t_out, rh)
            results["pmv"].append(comfort.pmv)
            results["ppd"].append(comfort.ppd)
            results["optimal_setpoint"].append(t_opt)
            results["setpoint_delta"].append(t_opt - baseline_setpoint)

        return results
