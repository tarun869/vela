"""
Multi-zone building energy model.

Extends the single-zone RC model to a network of coupled zones with
inter-zone heat transfer via shared walls and HVAC zonal distribution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np

from .hvac_model import HVACModel, RCZoneParams


@dataclass
class ZoneConnection:
    """Thermal coupling between two zones through a shared partition."""
    zone_a: str
    zone_b: str
    r_partition: float   # Thermal resistance of shared wall (K/W)
    area_m2: float       # Shared wall area (m^2)


@dataclass
class BuildingConfig:
    """Configuration for a multi-zone building."""
    name: str
    zones: Dict[str, RCZoneParams]
    connections: List[ZoneConnection] = field(default_factory=list)
    total_floor_area_m2: float = 0.0


@dataclass
class ZoneResult:
    zone_id: str
    temperatures: List[float]
    hvac_powers_w: List[float]
    energy_kwh: float


class BuildingModel:
    """
    Multi-zone building thermal model.

    Each zone is an RC circuit; zones exchange heat through shared partitions.
    HVAC dispatch is per-zone and independent.
    """

    def __init__(self, config: BuildingConfig, initial_temps: Optional[Dict[str, float]] = None) -> None:
        self.config = config
        self._zone_models: Dict[str, HVACModel] = {}

        for zone_id, params in config.zones.items():
            t_init = (initial_temps or {}).get(zone_id, 22.0)
            self._zone_models[zone_id] = HVACModel(params, t_zone_init=t_init)

        # Build adjacency for inter-zone coupling
        self._adjacency: Dict[str, List[ZoneConnection]] = {z: [] for z in config.zones}
        for conn in config.connections:
            self._adjacency[conn.zone_a].append(conn)
            self._adjacency[conn.zone_b].append(conn)

    def get_zone_temperatures(self) -> Dict[str, float]:
        return {zid: m.state.t_zone for zid, m in self._zone_models.items()}

    def _inter_zone_heat(self, zone_id: str) -> float:
        """Compute net heat flow into zone_id from all adjacent zones (W)."""
        t_self = self._zone_models[zone_id].state.t_zone
        q_net = 0.0
        for conn in self._adjacency[zone_id]:
            other_id = conn.zone_b if conn.zone_a == zone_id else conn.zone_a
            t_other = self._zone_models[other_id].state.t_zone
            q_net += (t_other - t_self) / conn.r_partition
        return q_net

    def step(
        self,
        dt_s: float,
        t_outdoor: float,
        hvac_dispatch_w: Dict[str, float],
        ghi_w_m2: float = 0.0,
        occupancy: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Advance all zones by dt_s seconds.

        Returns:
            Dict of zone_id -> new temperature (°C).
        """
        occupancy = occupancy or {}
        inter_zone_q: Dict[str, float] = {}
        for zone_id in self._zone_models:
            inter_zone_q[zone_id] = self._inter_zone_heat(zone_id)

        new_temps: Dict[str, float] = {}
        for zone_id, model in self._zone_models.items():
            q_hvac = hvac_dispatch_w.get(zone_id, 0.0) + inter_zone_q[zone_id]
            occ = occupancy.get(zone_id, 1.0)
            t_new = model.step(dt_s, t_outdoor, q_hvac, ghi_w_m2, occ)
            new_temps[zone_id] = t_new
        return new_temps

    def simulate(
        self,
        dt_s: float,
        t_outdoor_series: List[float],
        hvac_series: Dict[str, List[float]],
        ghi_series: Optional[List[float]] = None,
        occupancy_series: Optional[Dict[str, List[float]]] = None,
    ) -> Dict[str, ZoneResult]:
        """
        Run a full multi-zone simulation.

        Returns:
            Dict of zone_id -> ZoneResult with temperature and power profiles.
        """
        n = len(t_outdoor_series)
        ghi_series = ghi_series or [0.0] * n
        occupancy_series = occupancy_series or {}

        zone_temps: Dict[str, List[float]] = {z: [] for z in self._zone_models}
        zone_powers: Dict[str, List[float]] = {z: [] for z in self._zone_models}

        for i in range(n):
            occ_step = {z: occupancy_series[z][i] for z in occupancy_series}
            hvac_step = {z: hvac_series.get(z, [0.0] * n)[i] for z in self._zone_models}
            temps = self.step(dt_s, t_outdoor_series[i], hvac_step, ghi_series[i], occ_step)
            for z, t in temps.items():
                zone_temps[z].append(t)
                zone_powers[z].append(hvac_step.get(z, 0.0))

        results: Dict[str, ZoneResult] = {}
        for z in self._zone_models:
            energy_kwh = sum(abs(p) for p in zone_powers[z]) * dt_s / 3_600_000.0
            results[z] = ZoneResult(
                zone_id=z,
                temperatures=zone_temps[z],
                hvac_powers_w=zone_powers[z],
                energy_kwh=energy_kwh,
            )
        return results

    def total_hvac_power_w(self) -> float:
        """Sum of current HVAC power across all zones."""
        return sum(m.state.hvac_power_w for m in self._zone_models.values())

    def comfort_violations(
        self, zone_id: str, t_min: float, t_max: float, temperature_series: List[float]
    ) -> Tuple[int, float]:
        """
        Count comfort violations and compute degree-hour exceedance.

        Returns:
            (violation_count, degree_hours_violation)
        """
        violations = 0
        degree_hours = 0.0
        for t in temperature_series:
            if t < t_min:
                violations += 1
                degree_hours += (t_min - t)
            elif t > t_max:
                violations += 1
                degree_hours += (t - t_max)
        return violations, degree_hours / len(temperature_series) if temperature_series else 0.0

    def reset_all(self, initial_temps: Optional[Dict[str, float]] = None) -> None:
        initial_temps = initial_temps or {}
        for zone_id, model in self._zone_models.items():
            model.reset(initial_temps.get(zone_id, 22.0))


def create_office_building(n_floors: int = 3, zones_per_floor: int = 4) -> BuildingModel:
    """Factory: create a generic multi-floor office building model."""
    from .hvac_model import build_typical_office_params

    zone_area = 150.0  # m^2 per zone
    zones: Dict[str, RCZoneParams] = {}
    connections: List[ZoneConnection] = []

    for floor in range(n_floors):
        for z in range(zones_per_floor):
            zone_id = f"F{floor+1}Z{z+1}"
            zones[zone_id] = build_typical_office_params(zone_area)

            # Connect adjacent zones on same floor
            if z > 0:
                prev_id = f"F{floor+1}Z{z}"
                connections.append(ZoneConnection(
                    zone_a=prev_id,
                    zone_b=zone_id,
                    r_partition=0.05,  # K/W shared wall
                    area_m2=30.0,
                ))

    config = BuildingConfig(
        name=f"Office_{n_floors}F_{zones_per_floor}Z",
        zones=zones,
        connections=connections,
        total_floor_area_m2=zone_area * n_floors * zones_per_floor,
    )
    return BuildingModel(config)
