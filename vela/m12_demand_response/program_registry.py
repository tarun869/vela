"""
DR Program Registry — catalog of demand response programs including OpenADR and utility programs.

Manages program metadata, eligibility criteria, notice requirements,
payment structures, and enrollment tracking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional
import uuid


class ProgramType(str, Enum):
    EMERGENCY_DR = "emergency_dr"           # Emergency curtailment
    ECONOMIC_DR = "economic_dr"             # Price-responsive curtailment
    CAPACITY_DR = "capacity_dr"             # Capacity resource
    ANCILLARY_DR = "ancillary_dr"           # Ancillary services
    OPEN_ADR_2_0 = "open_adr_2_0"          # OpenADR 2.0b VTN program
    DEMAND_BIDDING = "demand_bidding"       # ISO demand bidding program
    INTERRUPTIBLE = "interruptible"         # Interruptible load tariff


class NoticeRequirement(str, Enum):
    REAL_TIME = "real_time"       # 0–15 minutes
    SHORT = "short"               # 15–120 minutes
    DAY_AHEAD = "day_ahead"       # 12–24 hours
    MULTI_DAY = "multi_day"       # > 24 hours


@dataclass
class PaymentStructure:
    capacity_payment_usd_kw_month: float = 0.0    # $/kW-month for enrollment
    energy_payment_usd_kwh: float = 0.0           # $/kWh for curtailed energy
    performance_bonus_usd_kwh: float = 0.0        # Bonus for exceeding target
    penalty_usd_kwh: float = 0.0                  # Penalty for non-performance
    baseline_method: str = "day_of_week_10"       # Baseline methodology


@dataclass
class DRProgram:
    program_id: str
    name: str
    program_type: ProgramType
    iso_rto: str                          # e.g., "ERCOT", "CAISO", "PJM", "MISO"
    utility: Optional[str]
    notice_requirement: NoticeRequirement
    min_capacity_kw: float                # Minimum enrollment threshold (kW)
    max_duration_h: float                 # Maximum event duration (hours)
    max_events_per_year: int
    max_hours_per_year: float
    payment: PaymentStructure
    open_adr_ven_url: Optional[str] = None
    enrollment_open: bool = True
    program_start: Optional[datetime] = None
    program_end: Optional[datetime] = None
    description: str = ""


@dataclass
class Enrollment:
    enrollment_id: str
    program_id: str
    site_id: str
    enrolled_capacity_kw: float
    baseline_load_kw: float
    enrolled_at: datetime = field(default_factory=datetime.utcnow)
    active: bool = True
    events_participated: int = 0
    hours_participated: float = 0.0
    total_earnings_usd: float = 0.0
    performance_score: float = 1.0   # 0–1 performance factor


class DRProgramRegistry:
    """
    Central registry for all demand response programs.
    Manages enrollment, eligibility checks, and payment calculations.
    """

    def __init__(self) -> None:
        self._programs: Dict[str, DRProgram] = {}
        self._enrollments: Dict[str, List[Enrollment]] = {}  # site_id -> enrollments

    def register_program(self, program: DRProgram) -> None:
        self._programs[program.program_id] = program

    def get_program(self, program_id: str) -> DRProgram:
        if program_id not in self._programs:
            raise KeyError(f"Program '{program_id}' not found")
        return self._programs[program_id]

    def list_programs(
        self, iso: Optional[str] = None, program_type: Optional[ProgramType] = None
    ) -> List[DRProgram]:
        programs = list(self._programs.values())
        if iso:
            programs = [p for p in programs if p.iso_rto == iso]
        if program_type:
            programs = [p for p in programs if p.program_type == program_type]
        return programs

    def enroll(
        self,
        site_id: str,
        program_id: str,
        capacity_kw: float,
        baseline_kw: float,
    ) -> Enrollment:
        """Enroll a site in a DR program."""
        program = self.get_program(program_id)

        if not program.enrollment_open:
            raise ValueError(f"Program '{program_id}' is not accepting enrollments")
        if capacity_kw < program.min_capacity_kw:
            raise ValueError(
                f"Capacity {capacity_kw} kW below minimum {program.min_capacity_kw} kW"
            )

        # Check no duplicate enrollment
        existing = self._enrollments.get(site_id, [])
        for enr in existing:
            if enr.program_id == program_id and enr.active:
                raise ValueError(f"Site already enrolled in program '{program_id}'")

        enrollment = Enrollment(
            enrollment_id=str(uuid.uuid4()),
            program_id=program_id,
            site_id=site_id,
            enrolled_capacity_kw=capacity_kw,
            baseline_load_kw=baseline_kw,
        )
        self._enrollments.setdefault(site_id, []).append(enrollment)
        return enrollment

    def unenroll(self, site_id: str, program_id: str) -> bool:
        for enr in self._enrollments.get(site_id, []):
            if enr.program_id == program_id and enr.active:
                enr.active = False
                return True
        return False

    def site_enrollments(self, site_id: str, active_only: bool = True) -> List[Enrollment]:
        enrollments = self._enrollments.get(site_id, [])
        return [e for e in enrollments if not active_only or e.active]

    def eligible_programs(self, site_id: str, capacity_kw: float) -> List[DRProgram]:
        """Return programs for which this site is eligible but not yet enrolled."""
        enrolled_ids = {e.program_id for e in self.site_enrollments(site_id)}
        return [
            p for p in self._programs.values()
            if p.enrollment_open
            and p.program_id not in enrolled_ids
            and capacity_kw >= p.min_capacity_kw
        ]

    def calculate_monthly_payment(self, enrollment: Enrollment, curtailed_kwh: float) -> float:
        """Calculate monthly DR payment for an enrollment."""
        prog = self.get_program(enrollment.program_id)
        pmt = prog.payment

        capacity_payment = pmt.capacity_payment_usd_kw_month * enrollment.enrolled_capacity_kw
        energy_payment = pmt.energy_payment_usd_kwh * curtailed_kwh * enrollment.performance_score
        bonus = (
            pmt.performance_bonus_usd_kwh * curtailed_kwh
            if enrollment.performance_score > 1.0 else 0.0
        )
        total = capacity_payment + energy_payment + bonus
        enrollment.total_earnings_usd += total
        return total

    def record_event_participation(
        self, enrollment: Enrollment, duration_h: float, curtailed_kw: float
    ) -> None:
        enrollment.events_participated += 1
        enrollment.hours_participated += duration_h
        performance = curtailed_kw / max(1.0, enrollment.enrolled_capacity_kw)
        enrollment.performance_score = 0.9 * enrollment.performance_score + 0.1 * performance


def build_ercot_programs() -> List[DRProgram]:
    """Pre-populated ERCOT demand response programs."""
    return [
        DRProgram(
            program_id="ERCOT_ERS",
            name="Emergency Response Service",
            program_type=ProgramType.EMERGENCY_DR,
            iso_rto="ERCOT",
            utility=None,
            notice_requirement=NoticeRequirement.SHORT,
            min_capacity_kw=100.0,
            max_duration_h=4.0,
            max_events_per_year=30,
            max_hours_per_year=60.0,
            payment=PaymentStructure(
                capacity_payment_usd_kw_month=2.50,
                energy_payment_usd_kwh=0.05,
                performance_bonus_usd_kwh=0.10,
                penalty_usd_kwh=0.25,
            ),
            description="ERCOT Emergency Response Service for reliability events",
        ),
        DRProgram(
            program_id="ERCOT_LRS",
            name="Load Resource Service (4CP)",
            program_type=ProgramType.CAPACITY_DR,
            iso_rto="ERCOT",
            utility=None,
            notice_requirement=NoticeRequirement.DAY_AHEAD,
            min_capacity_kw=1000.0,
            max_duration_h=1.0,
            max_events_per_year=4,
            max_hours_per_year=4.0,
            payment=PaymentStructure(
                capacity_payment_usd_kw_month=8.0,
                energy_payment_usd_kwh=0.0,
            ),
            description="4 Coincident Peak capacity program",
        ),
    ]
