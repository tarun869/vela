"""Asset enrollment in demand response and ancillary service programs."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from vela.portfolio.models import AssetProfile, Enrollment, Portfolio, Program

logger = logging.getLogger(__name__)


class EnrollmentManager:
    """
    Manages the lifecycle of asset-to-program enrollments.
    Validates eligibility, creates enrollment records, and tracks expirations.
    """

    def __init__(self, portfolio: Portfolio) -> None:
        self.portfolio = portfolio

    def enroll(
        self,
        asset_id: str,
        program_id: str,
        enrolled_mw: float | None = None,
        expires_at: datetime | None = None,
        contract_id: str | None = None,
    ) -> Enrollment:
        """
        Enroll an asset in a program.
        Raises ValueError if the asset or program is not found, or if eligibility fails.
        """
        asset = self._get_asset(asset_id)
        program = self._get_program(program_id)

        self._check_eligibility(asset, program, enrolled_mw or asset.power_mw)

        # Determine enrolled MW
        mw = enrolled_mw if enrolled_mw is not None else asset.power_mw
        if program.max_asset_mw is not None:
            mw = min(mw, program.max_asset_mw)

        enrollment = Enrollment(
            enrollment_id=str(uuid.uuid4()),
            asset_id=asset_id,
            program_id=program_id,
            enrolled_mw=mw,
            enrolled_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            status="active",
            contract_id=contract_id,
        )
        self.portfolio.enrollments.append(enrollment)
        logger.info(
            "Enrolled asset=%s in program=%s mw=%.2f", asset_id, program_id, mw
        )
        return enrollment

    def terminate(self, enrollment_id: str, reason: str = "") -> Enrollment:
        """Terminate an active enrollment."""
        enrollment = self._get_enrollment(enrollment_id)
        if enrollment.status not in ("active", "pending"):
            raise ValueError(f"Cannot terminate enrollment in status '{enrollment.status}'")
        enrollment.status = "terminated"
        logger.info("Terminated enrollment=%s reason=%s", enrollment_id, reason)
        return enrollment

    def get_active_enrollments(self, asset_id: str | None = None) -> list[Enrollment]:
        """Return all currently active enrollments, optionally filtered by asset."""
        now = datetime.now(timezone.utc)
        active = [e for e in self.portfolio.enrollments if e.is_active]
        if asset_id:
            active = [e for e in active if e.asset_id == asset_id]
        return active

    def get_enrolled_capacity(self, program_id: str) -> float:
        """Return total enrolled MW for a program across all active assets."""
        return sum(
            e.enrolled_mw
            for e in self.get_active_enrollments()
            if e.program_id == program_id
        )

    def check_program_minimum(self, program_id: str) -> bool:
        """Return True if the program's minimum portfolio MW requirement is met."""
        program = self._get_program(program_id)
        enrolled = self.get_enrolled_capacity(program_id)
        return enrolled >= program.min_portfolio_mw

    def _check_eligibility(self, asset: AssetProfile, program: Program, mw: float) -> None:
        if not program.active:
            raise ValueError(f"Program '{program.program_id}' is not accepting enrollments")
        if mw < program.min_asset_mw:
            raise ValueError(
                f"Asset power {mw:.2f} MW is below program minimum {program.min_asset_mw:.2f} MW"
            )
        # Check for duplicate enrollment
        for e in self.portfolio.enrollments:
            if e.asset_id == asset.asset_id and e.program_id == program.program_id and e.is_active:
                raise ValueError(
                    f"Asset '{asset.asset_id}' is already enrolled in program '{program.program_id}'"
                )

    def _get_asset(self, asset_id: str) -> AssetProfile:
        for a in self.portfolio.assets:
            if a.asset_id == asset_id:
                return a
        raise ValueError(f"Asset '{asset_id}' not found in portfolio")

    def _get_program(self, program_id: str) -> Program:
        for p in self.portfolio.programs:
            if p.program_id == program_id:
                return p
        raise ValueError(f"Program '{program_id}' not found in portfolio")

    def _get_enrollment(self, enrollment_id: str) -> Enrollment:
        for e in self.portfolio.enrollments:
            if e.enrollment_id == enrollment_id:
                return e
        raise ValueError(f"Enrollment '{enrollment_id}' not found")
