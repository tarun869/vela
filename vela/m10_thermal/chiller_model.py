"""
Chiller / cooling plant model with COP curves.

Models an electric centrifugal or screw chiller including:
  - Part-load COP curve (IPLV/NPLV methodology)
  - Condenser water temperature influence on COP
  - Chilled water supply/return temperature tracking
  - Demand-side thermal storage integration hook
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple
import numpy as np


class ChillerType(str, Enum):
    CENTRIFUGAL = "centrifugal"
    SCREW = "screw"
    SCROLL = "scroll"
    ABSORPTION = "absorption"


@dataclass
class ChillerParams:
    """Nameplate and performance parameters for a chiller unit."""
    chiller_id: str
    chiller_type: ChillerType
    capacity_kw: float           # Rated cooling capacity (kW)
    cop_rated: float             # COP at rated conditions (ARI 550/590)
    t_chws_design: float = 6.7   # Chilled water supply setpoint (°C) — 44°F
    t_cws_design: float = 29.4   # Condenser water supply (°C) — 85°F
    min_plr: float = 0.10        # Minimum part-load ratio
    max_plr: float = 1.05        # Maximum overload ratio

    def __post_init__(self) -> None:
        if self.capacity_kw <= 0:
            raise ValueError("capacity_kw must be positive")
        if not (0 < self.min_plr < self.max_plr):
            raise ValueError("0 < min_plr < max_plr required")


@dataclass
class ChillerState:
    plr: float = 0.0              # Current part-load ratio
    q_cooling_kw: float = 0.0    # Cooling output (kW)
    p_electric_kw: float = 0.0   # Electrical input (kW)
    cop_actual: float = 0.0      # Actual COP
    t_chws: float = 6.7          # Chilled water supply temp (°C)
    t_chwr: float = 12.2         # Chilled water return temp (°C)
    running: bool = False


class ChillerModel:
    """
    Chiller model with part-load performance curve.

    COP correction uses DOE-2 bi-quadratic curves:
      COP_adj = COP_rated * f(PLR) * g(T_condenser) * h(T_evap)
    """

    # Coefficients for centrifugal chiller PLR-COP curve (polynomial fit)
    _PLR_COP_COEFF: dict = {
        ChillerType.CENTRIFUGAL: [0.0, 1.32, -0.77, 0.45],   # a0..a3
        ChillerType.SCREW:       [0.0, 0.95, 0.15, -0.10],
        ChillerType.SCROLL:      [0.0, 0.90, 0.20, -0.10],
        ChillerType.ABSORPTION:  [0.0, 0.80, 0.30, -0.10],
    }

    def __init__(self, params: ChillerParams) -> None:
        self.params = params
        self.state = ChillerState(t_chws=params.t_chws_design)

    def _plr_cop_factor(self, plr: float) -> float:
        """Polynomial fit: COP / COP_rated as function of PLR."""
        coeff = self._PLR_COP_COEFF.get(
            self.params.chiller_type, self._PLR_COP_COEFF[ChillerType.CENTRIFUGAL]
        )
        plr_clipped = max(self.params.min_plr, min(plr, self.params.max_plr))
        return coeff[0] + coeff[1] * plr_clipped + coeff[2] * plr_clipped**2 + coeff[3] * plr_clipped**3

    def _condenser_cop_factor(self, t_cws: float) -> float:
        """
        Adjust COP for condenser water temperature deviation.
        Warmer condenser water reduces COP.
        """
        dt = t_cws - self.params.t_cws_design
        return max(0.5, 1.0 - 0.015 * dt)  # ~1.5% degradation per K above design

    def _evap_cop_factor(self, t_chws: float) -> float:
        """Adjust COP for chilled water supply temperature deviation."""
        dt = t_chws - self.params.t_chws_design
        return max(0.7, 1.0 + 0.008 * dt)  # Lower CHWS temp reduces COP

    def compute_cop(self, plr: float, t_cws: float = None, t_chws: float = None) -> float:
        """Compute actual COP at given operating conditions."""
        t_cws = t_cws if t_cws is not None else self.params.t_cws_design
        t_chws = t_chws if t_chws is not None else self.params.t_chws_design

        cop = (
            self.params.cop_rated
            * self._plr_cop_factor(plr)
            * self._condenser_cop_factor(t_cws)
            * self._evap_cop_factor(t_chws)
        )
        return max(0.5, cop)

    def dispatch(
        self,
        q_requested_kw: float,
        t_cws: Optional[float] = None,
        t_chws: Optional[float] = None,
    ) -> ChillerState:
        """
        Dispatch chiller to meet a requested cooling load.

        Returns updated ChillerState.
        """
        t_cws = t_cws if t_cws is not None else self.params.t_cws_design
        t_chws = t_chws if t_chws is not None else self.params.t_chws_design

        if q_requested_kw < self.params.capacity_kw * self.params.min_plr:
            # Below minimum load — turn off
            self.state = ChillerState(
                plr=0.0, q_cooling_kw=0.0, p_electric_kw=0.0,
                cop_actual=0.0, t_chws=t_chws, running=False
            )
            return self.state

        plr = min(q_requested_kw / self.params.capacity_kw, self.params.max_plr)
        q_actual = plr * self.params.capacity_kw
        cop = self.compute_cop(plr, t_cws, t_chws)
        p_electric = q_actual / cop

        # Chilled water return temperature (simplified energy balance)
        # Q = m_dot * Cp * dT => assume fixed flow, vary dT
        flow_kg_s = self.params.capacity_kw / (4.18 * 5.5)  # design dT = 5.5 K
        t_chwr = t_chws + q_actual / (flow_kg_s * 4.18)

        self.state = ChillerState(
            plr=plr,
            q_cooling_kw=q_actual,
            p_electric_kw=p_electric,
            cop_actual=cop,
            t_chws=t_chws,
            t_chwr=t_chwr,
            running=True,
        )
        return self.state

    def iplv(self) -> float:
        """
        Integrated Part-Load Value (IPLV) — weighted average COP.
        Uses ARI 550/590 weighting: 1%@100%, 42%@75%, 45%@50%, 12%@25%.
        """
        weights = [(1.00, 0.01), (0.75, 0.42), (0.50, 0.45), (0.25, 0.12)]
        return sum(self.compute_cop(plr) * w for plr, w in weights)

    def annual_energy_kwh(self, load_profile_kw: List[float], dt_h: float = 1.0) -> float:
        """Estimate annual electrical energy consumption from cooling load profile."""
        total = 0.0
        for q in load_profile_kw:
            if q > 0:
                plr = min(q / self.params.capacity_kw, self.params.max_plr)
                cop = self.compute_cop(plr)
                total += (q / cop) * dt_h
        return total


class ChillerPlant:
    """Multiple chillers operating in lead-lag configuration."""

    def __init__(self, chillers: List[ChillerModel]) -> None:
        self.chillers = sorted(chillers, key=lambda c: c.params.capacity_kw, reverse=True)

    def dispatch_plant(self, q_total_kw: float, t_cws: float = None) -> Tuple[float, float, float]:
        """
        Lead-lag dispatch across multiple chillers.

        Returns:
            (q_served_kw, p_electric_total_kw, plant_cop)
        """
        remaining = q_total_kw
        p_total = 0.0
        q_total_served = 0.0

        for chiller in self.chillers:
            if remaining <= 0:
                chiller.dispatch(0, t_cws)
                continue
            q_this = min(remaining, chiller.params.capacity_kw * chiller.params.max_plr)
            state = chiller.dispatch(q_this, t_cws)
            remaining -= state.q_cooling_kw
            p_total += state.p_electric_kw
            q_total_served += state.q_cooling_kw

        plant_cop = q_total_served / p_total if p_total > 0 else 0.0
        return q_total_served, p_total, plant_cop
