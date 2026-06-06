"""
Asset health scoring for VPP battery, solar, and wind resources.

Combines electrochemical degradation, cycle stress, and operational
history into a composite 0–100 health score per asset.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class AssetHealthData:
    asset_id: str
    asset_type: str             # "battery", "solar_pv", "wind_turbine", "inverter"
    age_years: float
    design_lifetime_years: float
    total_cycles: int           # Battery: full equivalent cycles
    dod_history_pct: List[float]   # Last N discharge depths
    temperature_history_c: List[float]
    capacity_retained_pct: float    # Measured capacity vs nameplate
    recent_faults: int             # Faults in last 30 days


@dataclass
class HealthScoreResult:
    asset_id: str
    overall_score: float        # 0–100 (100 = new)
    electrochemical_score: float
    thermal_score: float
    cycling_score: float
    age_score: float
    maintenance_score: float
    recommended_action: str


# Action thresholds
SCORE_THRESHOLDS = {
    "excellent": 85,
    "good": 70,
    "fair": 55,
    "poor": 40,
}


class AssetHealthScorer:
    """
    Computes composite health scores for VPP assets.

    Weights are calibrated to battery storage; other asset types
    can override with different weight profiles.
    """

    BATTERY_WEIGHTS = {
        "electrochemical": 0.35,
        "thermal": 0.20,
        "cycling": 0.25,
        "age": 0.15,
        "maintenance": 0.05,
    }

    def score(self, data: AssetHealthData) -> HealthScoreResult:
        """Compute composite health score from asset telemetry."""
        # Electrochemical: based on capacity retention
        electro = np.clip(data.capacity_retained_pct, 0.0, 100.0)

        # Thermal: penalize high average temperature (Arrhenius)
        avg_temp = np.mean(data.temperature_history_c) if data.temperature_history_c else 25.0
        # SOH penalty: 2x faster aging per 10°C above 25°C (Arrhenius)
        temp_penalty = 2 ** ((avg_temp - 25.0) / 10.0) - 1.0
        thermal = max(0.0, 100.0 - temp_penalty * 15.0)

        # Cycling: compare actual cycles to manufacturer max (typically 3000–6000)
        design_cycles = 4000 if data.asset_type == "battery" else 999999
        cycle_fraction = min(1.0, data.total_cycles / design_cycles)
        cycling = 100.0 * (1 - cycle_fraction)

        # Age: linear derating
        age_fraction = min(1.0, data.age_years / max(data.design_lifetime_years, 1.0))
        age = 100.0 * (1 - age_fraction)

        # Maintenance: penalize recent faults
        maintenance = max(0.0, 100.0 - data.recent_faults * 10.0)

        w = self.BATTERY_WEIGHTS
        overall = (
            w["electrochemical"] * electro
            + w["thermal"] * thermal
            + w["cycling"] * cycling
            + w["age"] * age
            + w["maintenance"] * maintenance
        )

        # Determine recommended action
        if overall >= SCORE_THRESHOLDS["excellent"]:
            action = "normal_operation"
        elif overall >= SCORE_THRESHOLDS["good"]:
            action = "monitor_closely"
        elif overall >= SCORE_THRESHOLDS["fair"]:
            action = "schedule_inspection"
        elif overall >= SCORE_THRESHOLDS["poor"]:
            action = "immediate_maintenance"
        else:
            action = "consider_replacement"

        return HealthScoreResult(
            asset_id=data.asset_id,
            overall_score=round(overall, 1),
            electrochemical_score=round(electro, 1),
            thermal_score=round(thermal, 1),
            cycling_score=round(cycling, 1),
            age_score=round(age, 1),
            maintenance_score=round(maintenance, 1),
            recommended_action=action,
        )

    def fleet_health(self, assets: List[AssetHealthData]) -> Dict[str, float]:
        """Compute fleet-level health statistics."""
        scores = [self.score(a).overall_score for a in assets]
        return {
            "fleet_avg": float(np.mean(scores)) if scores else 0.0,
            "fleet_min": float(np.min(scores)) if scores else 0.0,
            "assets_below_70": sum(1 for s in scores if s < 70),
            "assets_critical": sum(1 for s in scores if s < 40),
        }
