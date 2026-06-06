"""
Black start capability modeling for VPP resources.

Black start resources can energize a de-energized power system
without an external power supply, supporting grid restoration.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


class BlackStartType(str, Enum):
    COMBUSTION_TURBINE = "combustion_turbine"
    HYDRO = "hydro"
    BATTERY_BACKED = "battery_backed"
    DIESEL_GEN = "diesel_gen"


@dataclass
class BlackStartResource:
    resource_id: str
    bs_type: BlackStartType
    capacity_mw: float
    startup_time_min: float       # Time to reach rated output from cold start
    fuel_onsite_days: float       # Days of fuel available without resupply
    cranking_path_kv: float       # Voltage level for cranking path
    local_black_start: bool       # Can restore local area without ISO instruction
    ferc_qualified: bool = False  # FERC Order 828 qualification
    annual_test_completed: bool = True


@dataclass
class RestorationPlan:
    plan_id: str
    sequence: List[str]          # Ordered list of resource_ids to energize
    estimated_restoration_h: float
    reliability_score: float     # 0–1


class BlackStartManager:
    """
    Manages black start capability assessment and restoration planning.
    """

    def __init__(self, iso: str = "ERCOT") -> None:
        self.iso = iso
        self._resources: Dict[str, BlackStartResource] = {}

    def register(self, resource: BlackStartResource) -> None:
        self._resources[resource.resource_id] = resource

    def ferc_qualification_check(self, resource_id: str) -> Tuple[bool, List[str]]:
        """Check FERC Order 828 black start qualification requirements."""
        res = self._resources.get(resource_id)
        if not res:
            return False, ["Resource not found"]
        gaps: List[str] = []
        if res.startup_time_min > 90:
            gaps.append("Startup time must be < 90 minutes for FERC qualification")
        if res.fuel_onsite_days < 7:
            gaps.append("Minimum 7 days of fuel required")
        if not res.annual_test_completed:
            gaps.append("Annual black start test not completed")
        return len(gaps) == 0, gaps

    def build_restoration_sequence(
        self,
        load_centers: List[str],
        priority_loads: List[str],
    ) -> RestorationPlan:
        """Build priority-ordered restoration sequence."""
        import uuid
        available = sorted(
            [r for r in self._resources.values() if r.ferc_qualified and r.annual_test_completed],
            key=lambda r: r.startup_time_min
        )
        sequence = [r.resource_id for r in available]
        total_time = sum(r.startup_time_min for r in available[:3]) / 60.0 if available else 12.0
        return RestorationPlan(
            plan_id=str(uuid.uuid4())[:8],
            sequence=sequence,
            estimated_restoration_h=total_time,
            reliability_score=len(available) / max(len(self._resources), 1),
        )
