"""
Heat pump model with COP curve and reversible heating/cooling.

Covers air-source (ASHP) and ground-source (GSHP) heat pumps,
with temperature-dependent COP using Carnot-referenced efficiency.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


class HeatPumpType(str, Enum):
    AIR_SOURCE = "air_source"
    GROUND_SOURCE = "ground_source"
    WATER_SOURCE = "water_source"


class OperatingMode(str, Enum):
    HEATING = "heating"
    COOLING = "cooling"
    OFF = "off"


@dataclass
class HeatPumpParams:
    hp_id: str
    hp_type: HeatPumpType
    capacity_heating_kw: float   # Rated heating capacity (kW) at design conditions
    capacity_cooling_kw: float   # Rated cooling capacity (kW) at design conditions
    cop_heating_rated: float     # COP heating at rated conditions (e.g. 47°F / 70°F)
    cop_cooling_rated: float     # COP cooling (EER/3.412) at rated conditions
    t_source_design: float       # Design source temperature (°C) — outdoor air or ground
    t_sink_design: float = 21.0  # Design sink (space) temperature (°C)
    min_source_temp: float = -15.0  # Minimum operating source temp (°C)
    defrost_below: float = 2.0   # Enable defrost cycle below this temp (°C) [ASHP only]
    carnot_fraction: float = 0.45  # Fraction of Carnot COP achievable


@dataclass
class HeatPumpState:
    mode: OperatingMode = OperatingMode.OFF
    q_delivered_kw: float = 0.0   # Thermal output (kW)
    p_electric_kw: float = 0.0    # Electrical input (kW)
    cop_actual: float = 0.0
    defrost_active: bool = False
    t_source: float = 10.0
    t_sink: float = 21.0


class HeatPumpModel:
    """
    Heat pump with temperature-dependent COP using modified Carnot approach.

    COP_heating = eta_carnot * T_sink / (T_sink - T_source)
    COP_cooling = eta_carnot * T_source / (T_sink - T_source)

    where temperatures are in Kelvin and eta_carnot is the Carnot fraction.
    """

    def __init__(self, params: HeatPumpParams) -> None:
        self.params = params
        self.state = HeatPumpState()

    def _carnot_cop_heating(self, t_source_c: float, t_sink_c: float) -> float:
        """Theoretical maximum COP for heating."""
        t_source_k = t_source_c + 273.15
        t_sink_k = t_sink_c + 273.15
        if t_sink_k <= t_source_k:
            return 10.0  # Degenerate case
        return t_sink_k / (t_sink_k - t_source_k)

    def _carnot_cop_cooling(self, t_source_c: float, t_sink_c: float) -> float:
        """Theoretical maximum COP for cooling (= EER/3.412)."""
        t_source_k = t_source_c + 273.15
        t_sink_k = t_sink_c + 273.15
        if t_sink_k <= t_source_k:
            return 10.0
        return t_source_k / (t_sink_k - t_source_k)

    def _defrost_penalty(self, t_source: float) -> float:
        """
        Defrost cycle penalty for ASHP — reduces effective COP.
        Linear ramp from 0 at defrost_below+4 to 0.15 penalty at min_source.
        """
        if self.params.hp_type != HeatPumpType.AIR_SOURCE:
            return 0.0
        if t_source >= self.params.defrost_below:
            return 0.0
        t_range = self.params.defrost_below - self.params.min_source_temp
        fraction = (self.params.defrost_below - t_source) / t_range if t_range > 0 else 1.0
        return min(0.20, 0.20 * fraction)

    def cop_heating(self, t_source: float, t_sink: float = None) -> float:
        """Actual heating COP at given temperatures."""
        t_sink = t_sink if t_sink is not None else self.params.t_sink_design
        carnot = self._carnot_cop_heating(t_source, t_sink)
        cop = self.params.carnot_fraction * carnot
        defrost = self._defrost_penalty(t_source)
        return max(1.0, cop * (1.0 - defrost))

    def cop_cooling(self, t_source: float, t_sink: float = None) -> float:
        """Actual cooling COP at given temperatures."""
        t_sink = t_sink if t_sink is not None else self.params.t_sink_design
        carnot = self._carnot_cop_cooling(t_source, t_sink)
        cop = self.params.carnot_fraction * carnot
        return max(0.5, cop)

    def max_heating_capacity(self, t_source: float) -> float:
        """
        Derate heating capacity at low source temperatures.
        ASHP capacity drops ~1.5% per °C below design.
        """
        if self.params.hp_type == HeatPumpType.GROUND_SOURCE:
            return self.params.capacity_heating_kw  # GSHP relatively constant
        dt = self.params.t_source_design - t_source
        derate = max(0.4, 1.0 - 0.015 * max(0, dt))
        return self.params.capacity_heating_kw * derate

    def dispatch(
        self,
        mode: OperatingMode,
        q_requested_kw: float,
        t_source: float,
        t_sink: Optional[float] = None,
    ) -> HeatPumpState:
        """
        Dispatch heat pump in heating or cooling mode.

        Returns:
            Updated HeatPumpState.
        """
        t_sink = t_sink if t_sink is not None else self.params.t_sink_design

        if mode == OperatingMode.OFF or q_requested_kw <= 0:
            self.state = HeatPumpState(mode=OperatingMode.OFF, t_source=t_source, t_sink=t_sink)
            return self.state

        if t_source < self.params.min_source_temp:
            # Cannot operate below minimum source temperature
            self.state = HeatPumpState(mode=OperatingMode.OFF, t_source=t_source, t_sink=t_sink)
            return self.state

        defrost = t_source < self.params.defrost_below and self.params.hp_type == HeatPumpType.AIR_SOURCE

        if mode == OperatingMode.HEATING:
            cap = self.max_heating_capacity(t_source)
            q_actual = min(q_requested_kw, cap)
            cop = self.cop_heating(t_source, t_sink)
        else:  # COOLING
            q_actual = min(q_requested_kw, self.params.capacity_cooling_kw)
            cop = self.cop_cooling(t_source, t_sink)

        p_electric = q_actual / cop
        self.state = HeatPumpState(
            mode=mode,
            q_delivered_kw=q_actual,
            p_electric_kw=p_electric,
            cop_actual=cop,
            defrost_active=defrost,
            t_source=t_source,
            t_sink=t_sink,
        )
        return self.state

    def seasonal_performance_factor(
        self,
        mode: OperatingMode,
        t_source_profile: List[float],
        load_profile_kw: List[float],
    ) -> float:
        """
        Compute Seasonal Performance Factor (SPF = SCOP or SEER).

        Returns:
            Total thermal output / total electrical input over the season.
        """
        total_thermal = 0.0
        total_electric = 0.0
        for t_src, q_req in zip(t_source_profile, load_profile_kw):
            state = self.dispatch(mode, q_req, t_src)
            total_thermal += state.q_delivered_kw
            total_electric += state.p_electric_kw
        return total_thermal / total_electric if total_electric > 0 else 0.0

    def breakeven_vs_resistive(self, t_source: float) -> float:
        """
        Temperature below which heat pump COP drops below 1.0 (resistance heating breakeven).
        """
        # Binary search for breakeven point
        t_low, t_high = self.params.min_source_temp, t_source
        for _ in range(50):
            t_mid = (t_low + t_high) / 2.0
            if self.cop_heating(t_mid) > 1.0:
                t_high = t_mid
            else:
                t_low = t_mid
        return (t_low + t_high) / 2.0


def create_residential_ashp(capacity_kw: float = 7.0) -> HeatPumpModel:
    """Create a typical residential air-source heat pump."""
    return HeatPumpModel(HeatPumpParams(
        hp_id="ASHP_residential",
        hp_type=HeatPumpType.AIR_SOURCE,
        capacity_heating_kw=capacity_kw,
        capacity_cooling_kw=capacity_kw * 0.95,
        cop_heating_rated=3.2,
        cop_cooling_rated=4.1,
        t_source_design=8.3,    # 47°F AHRI rating condition
        t_sink_design=21.0,
        min_source_temp=-15.0,
        defrost_below=2.0,
        carnot_fraction=0.42,
    ))


def create_commercial_gshp(capacity_kw: float = 50.0) -> HeatPumpModel:
    """Create a commercial ground-source heat pump."""
    return HeatPumpModel(HeatPumpParams(
        hp_id="GSHP_commercial",
        hp_type=HeatPumpType.GROUND_SOURCE,
        capacity_heating_kw=capacity_kw,
        capacity_cooling_kw=capacity_kw,
        cop_heating_rated=4.5,
        cop_cooling_rated=5.2,
        t_source_design=10.0,   # Ground loop temperature
        t_sink_design=21.0,
        min_source_temp=4.0,
        defrost_below=-999.0,   # No defrost needed
        carnot_fraction=0.52,
    ))
