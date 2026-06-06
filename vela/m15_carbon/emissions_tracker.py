"""
Real-time CO2 emissions tracking for VPP dispatch.

Tracks marginal emissions using grid emission factors (lbs CO2/MWh)
and computes avoided emissions from renewable dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import numpy as np


# NERC eGRID region emission rates (lbs CO2 / MWh) — 2023 values
EGRID_EMISSION_RATES: Dict[str, Dict[str, float]] = {
    "ERCOT": {"avg": 882, "marginal": 1100, "renewable_pct": 34.0},
    "CAISO": {"avg": 440, "marginal": 600, "renewable_pct": 52.0},
    "PJM": {"avg": 868, "marginal": 1050, "renewable_pct": 22.0},
    "MISO": {"avg": 988, "marginal": 1150, "renewable_pct": 18.0},
    "NYISO": {"avg": 401, "marginal": 520, "renewable_pct": 35.0},
    "ISONE": {"avg": 571, "marginal": 720, "renewable_pct": 29.0},
    "SPP": {"avg": 1012, "marginal": 1200, "renewable_pct": 42.0},
}

LBS_TO_KG = 0.453592
MWH_TO_KWH = 1000.0


@dataclass
class EmissionRecord:
    timestamp: str
    iso_rto: str
    energy_kwh: float
    emission_factor_lbs_mwh: float
    co2_lbs: float
    co2_kg: float
    is_renewable: bool
    avoided_co2_lbs: float    # vs. marginal grid


@dataclass
class EmissionsReport:
    period_start: str
    period_end: str
    iso_rto: str
    total_energy_kwh: float
    total_co2_lbs: float
    total_co2_kg: float
    total_co2_tonnes: float
    avoided_co2_tonnes: float   # vs. average grid emissions
    renewable_energy_kwh: float
    renewable_fraction: float
    avg_emission_intensity_lbs_mwh: float


class EmissionsTracker:
    """
    Tracks real-time emissions for VPP energy dispatch.

    Uses:
      - Marginal emission factors for value of dispatch decisions
      - Average emission factors for accounting/reporting
      - Time-varying emission rates (hourly if available)
    """

    def __init__(self, iso_rto: str, use_marginal: bool = True) -> None:
        self.iso_rto = iso_rto
        self.use_marginal = use_marginal
        self._records: List[EmissionRecord] = []
        self._hourly_factors: Optional[List[float]] = None  # Time-varying override

    @property
    def _base_rate(self) -> float:
        region = EGRID_EMISSION_RATES.get(self.iso_rto, {"avg": 800, "marginal": 1000})
        return region["marginal"] if self.use_marginal else region["avg"]

    def set_hourly_emission_factors(self, factors_lbs_mwh: List[float]) -> None:
        """Override with time-resolved emission factors (e.g., from WattTime API)."""
        self._hourly_factors = factors_lbs_mwh

    def _emission_factor(self, hour_of_day: int = 12) -> float:
        if self._hourly_factors and 0 <= hour_of_day < len(self._hourly_factors):
            return self._hourly_factors[hour_of_day]
        return self._base_rate

    def record_dispatch(
        self,
        energy_kwh: float,
        is_renewable: bool = False,
        hour_of_day: int = 12,
        timestamp: Optional[str] = None,
    ) -> EmissionRecord:
        """Record emissions for a dispatch event."""
        ef = self._emission_factor(hour_of_day)
        energy_mwh = energy_kwh / MWH_TO_KWH

        if is_renewable:
            co2_lbs = 0.0  # Zero-emission generation
        else:
            co2_lbs = ef * energy_mwh

        marginal_rate = EGRID_EMISSION_RATES.get(self.iso_rto, {}).get("marginal", 1000)
        avoided = (marginal_rate * energy_mwh) if is_renewable else 0.0

        record = EmissionRecord(
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            iso_rto=self.iso_rto,
            energy_kwh=energy_kwh,
            emission_factor_lbs_mwh=ef if not is_renewable else 0.0,
            co2_lbs=co2_lbs,
            co2_kg=co2_lbs * LBS_TO_KG,
            is_renewable=is_renewable,
            avoided_co2_lbs=avoided,
        )
        self._records.append(record)
        return record

    def generate_report(self, since: Optional[str] = None) -> EmissionsReport:
        """Generate emissions summary report."""
        records = self._records
        if since:
            records = [r for r in records if r.timestamp >= since]
        if not records:
            return EmissionsReport(
                period_start="", period_end="",
                iso_rto=self.iso_rto,
                total_energy_kwh=0, total_co2_lbs=0, total_co2_kg=0,
                total_co2_tonnes=0, avoided_co2_tonnes=0,
                renewable_energy_kwh=0, renewable_fraction=0,
                avg_emission_intensity_lbs_mwh=0
            )

        total_energy = sum(r.energy_kwh for r in records)
        total_co2_lbs = sum(r.co2_lbs for r in records)
        total_co2_kg = total_co2_lbs * LBS_TO_KG
        avoided_lbs = sum(r.avoided_co2_lbs for r in records)
        renewable_kwh = sum(r.energy_kwh for r in records if r.is_renewable)

        avg_intensity = (total_co2_lbs / (total_energy / MWH_TO_KWH)) if total_energy > 0 else 0.0

        return EmissionsReport(
            period_start=records[0].timestamp,
            period_end=records[-1].timestamp,
            iso_rto=self.iso_rto,
            total_energy_kwh=total_energy,
            total_co2_lbs=total_co2_lbs,
            total_co2_kg=total_co2_kg,
            total_co2_tonnes=total_co2_kg / 1000.0,
            avoided_co2_tonnes=avoided_lbs * LBS_TO_KG / 1000.0,
            renewable_energy_kwh=renewable_kwh,
            renewable_fraction=renewable_kwh / max(total_energy, 1.0),
            avg_emission_intensity_lbs_mwh=avg_intensity,
        )

    def carbon_intensity_forecast(self, hours: int = 24) -> List[float]:
        """
        Simple 24-hour carbon intensity forecast.

        Uses historical daily pattern: higher at peak hours, lower at night.
        """
        base = self._base_rate
        # Typical daily carbon intensity pattern (relative to base)
        pattern = [
            0.85, 0.82, 0.80, 0.79, 0.80, 0.85,
            0.92, 1.00, 1.08, 1.12, 1.10, 1.08,
            1.05, 1.05, 1.03, 1.02, 1.05, 1.15,
            1.18, 1.15, 1.10, 1.05, 0.98, 0.90,
        ]
        return [base * pattern[h % 24] for h in range(hours)]
