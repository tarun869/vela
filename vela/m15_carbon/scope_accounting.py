"""
Scope 1/2/3 emissions accounting per GHG Protocol corporate standard.

Provides structured accounting of greenhouse gas emissions across
all three scopes for VPP operations and the broader value chain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple


class EmissionScope(str, Enum):
    SCOPE_1 = "scope_1"   # Direct emissions from owned/controlled sources
    SCOPE_2 = "scope_2"   # Indirect from purchased electricity
    SCOPE_3 = "scope_3"   # All other indirect emissions


class Scope1Category(str, Enum):
    STATIONARY_COMBUSTION = "stationary_combustion"
    MOBILE_COMBUSTION = "mobile_combustion"
    FUGITIVE_EMISSIONS = "fugitive_emissions"
    PROCESS_EMISSIONS = "process_emissions"


class Scope3Category(str, Enum):
    PURCHASED_GOODS = "purchased_goods_services"
    CAPITAL_GOODS = "capital_goods"
    FUEL_ENERGY = "fuel_energy_activities"
    UPSTREAM_TRANSPORT = "upstream_transport"
    WASTE = "waste_in_operations"
    BUSINESS_TRAVEL = "business_travel"
    EMPLOYEE_COMMUTE = "employee_commuting"
    DOWNSTREAM_TRANSPORT = "downstream_transport"
    PROCESSING_SOLD = "processing_sold_products"
    USE_OF_SOLD = "use_of_sold_products"
    END_OF_LIFE = "end_of_life"
    INVESTMENTS = "investments"


# Emission factors (tonnes CO2e per unit)
EMISSION_FACTORS = {
    # Fuel combustion (tonnes CO2e / MMBtu)
    "natural_gas": 0.0530,
    "diesel": 0.0733,
    "gasoline": 0.0706,
    # Grid electricity (tonnes CO2e / MWh) — US average
    "us_grid_avg": 0.386,
    # Refrigerants (GWP, kg CO2e / kg leaked)
    "r410a": 2088.0,
    "sf6": 22800.0,    # Used in high-voltage switchgear
    # Battery materials (tonnes CO2e / tonne material)
    "lithium": 6.0,
    "cobalt": 8.0,
    "nickel": 6.5,
}


@dataclass
class EmissionEntry:
    entry_id: str
    scope: EmissionScope
    category: str
    activity_description: str
    activity_quantity: float
    activity_unit: str
    emission_factor: float
    emission_factor_unit: str
    co2e_tonnes: float
    reporting_year: int
    data_quality: str   # "measured", "calculated", "estimated"
    source: str
    created_at: str


class ScopeAccountingEngine:
    """
    GHG Protocol-compliant scope 1/2/3 accounting for VPP operations.
    """

    def __init__(self, entity_name: str, reporting_year: int) -> None:
        self.entity_name = entity_name
        self.reporting_year = reporting_year
        self._entries: List[EmissionEntry] = []

    def _add_entry(
        self,
        scope: EmissionScope,
        category: str,
        description: str,
        quantity: float,
        unit: str,
        ef: float,
        ef_unit: str,
        co2e: float,
        data_quality: str = "calculated",
        source: str = "internal",
    ) -> EmissionEntry:
        import uuid as _uuid
        entry = EmissionEntry(
            entry_id=str(_uuid.uuid4()),
            scope=scope,
            category=category,
            activity_description=description,
            activity_quantity=quantity,
            activity_unit=unit,
            emission_factor=ef,
            emission_factor_unit=ef_unit,
            co2e_tonnes=co2e,
            reporting_year=self.reporting_year,
            data_quality=data_quality,
            source=source,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._entries.append(entry)
        return entry

    # ---- Scope 1 ----

    def add_fuel_combustion(
        self,
        fuel_type: str,
        quantity_mmbtu: float,
        description: str = "On-site generator",
    ) -> float:
        """Add Scope 1 stationary combustion entry."""
        ef = EMISSION_FACTORS.get(fuel_type.lower(), 0.05)
        co2e = quantity_mmbtu * ef
        self._add_entry(
            EmissionScope.SCOPE_1, Scope1Category.STATIONARY_COMBUSTION.value,
            description, quantity_mmbtu, "MMBtu", ef, "tCO2e/MMBtu", co2e,
        )
        return co2e

    def add_fugitive_sf6(self, kg_leaked: float) -> float:
        """Add Scope 1 SF6 fugitive emissions from switchgear."""
        ef = EMISSION_FACTORS["sf6"]
        co2e = kg_leaked * ef / 1000.0  # kg to tonnes
        self._add_entry(
            EmissionScope.SCOPE_1, Scope1Category.FUGITIVE_EMISSIONS.value,
            "SF6 leakage from HV switchgear", kg_leaked, "kg", ef, "kg CO2e/kg", co2e,
        )
        return co2e

    # ---- Scope 2 ----

    def add_purchased_electricity(
        self,
        energy_mwh: float,
        grid_region: str = "US_avg",
        method: str = "location_based",
    ) -> float:
        """
        Add Scope 2 purchased electricity (location-based or market-based).
        """
        ef = EMISSION_FACTORS.get(grid_region.lower(), EMISSION_FACTORS["us_grid_avg"])
        # Market-based: use residual mix (lower if RECs retired)
        if method == "market_based":
            ef = ef * 0.6  # Simplified: assume 40% offset by RECs
        co2e = energy_mwh * ef
        self._add_entry(
            EmissionScope.SCOPE_2, f"purchased_electricity_{method}",
            f"Grid electricity ({grid_region}, {method})",
            energy_mwh, "MWh", ef, "tCO2e/MWh", co2e,
        )
        return co2e

    # ---- Scope 3 ----

    def add_capital_goods(
        self,
        asset_type: str,
        quantity_tonnes: float,
        ef_tco2e_per_tonne: float,
    ) -> float:
        """Add Scope 3 capital goods (battery materials, inverters, etc.)."""
        co2e = quantity_tonnes * ef_tco2e_per_tonne
        self._add_entry(
            EmissionScope.SCOPE_3, Scope3Category.CAPITAL_GOODS.value,
            f"Capital goods: {asset_type}", quantity_tonnes, "tonnes",
            ef_tco2e_per_tonne, "tCO2e/tonne", co2e,
        )
        return co2e

    def add_business_travel(self, km_air: float, km_car: float) -> float:
        """Add Scope 3 business travel emissions."""
        ef_air = 0.000255  # tCO2e/km
        ef_car = 0.000170
        co2e = km_air * ef_air + km_car * ef_car
        self._add_entry(
            EmissionScope.SCOPE_3, Scope3Category.BUSINESS_TRAVEL.value,
            f"Business travel ({km_air:.0f} km air, {km_car:.0f} km car)",
            km_air + km_car, "km", (co2e / (km_air + km_car + 1e-9)), "tCO2e/km", co2e,
        )
        return co2e

    # ---- Reporting ----

    def summary(self) -> Dict[str, float]:
        """Total emissions by scope (tCO2e)."""
        totals: Dict[str, float] = {s.value: 0.0 for s in EmissionScope}
        for e in self._entries:
            totals[e.scope.value] += e.co2e_tonnes
        totals["total"] = sum(totals.values())
        return totals

    def breakdown_by_category(self) -> Dict[str, Dict[str, float]]:
        """Emissions by scope and category."""
        result: Dict[str, Dict[str, float]] = {}
        for e in self._entries:
            scope_key = e.scope.value
            result.setdefault(scope_key, {})
            result[scope_key][e.category] = result[scope_key].get(e.category, 0.0) + e.co2e_tonnes
        return result

    def intensity_metrics(self, revenue_usd: float, employees: int) -> Dict[str, float]:
        """Compute emission intensity metrics."""
        total = sum(e.co2e_tonnes for e in self._entries)
        return {
            "tco2e_per_musd_revenue": total / (revenue_usd / 1e6) if revenue_usd > 0 else 0,
            "tco2e_per_employee": total / max(employees, 1),
            "total_tco2e": total,
        }
