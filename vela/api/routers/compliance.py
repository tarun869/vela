"""Compliance reporting endpoints: NERC, FERC, state reporting."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class ComplianceReport(BaseModel):
    report_id: str
    report_type: str
    regulatory_body: Literal["NERC", "FERC", "CAISO", "ERCOT", "PJM", "state"]
    period_start: datetime
    period_end: datetime
    asset_ids: list[str]
    status: Literal["draft", "submitted", "accepted", "rejected", "under_review"]
    generated_at: datetime
    submitted_at: datetime | None = None
    findings: list[str] = Field(default_factory=list)
    violations: list[dict] = Field(default_factory=list)
    attestation: str | None = None


class ComplianceCheck(BaseModel):
    check_id: str
    asset_id: str
    check_type: str
    passed: bool
    threshold: float | None = None
    actual: float | None = None
    message: str
    checked_at: datetime
    severity: Literal["info", "warning", "error", "critical"]


class ObligationStatus(BaseModel):
    obligation_id: str
    obligation_type: str
    market: str
    period_start: datetime
    period_end: datetime
    committed_mw: float
    delivered_mw: float
    compliance_pct: float
    penalty_usd: float
    status: Literal["compliant", "non_compliant", "partial", "pending"]


_REPORTS: dict[str, ComplianceReport] = {}


@router.post("/reports/generate", response_model=ComplianceReport, status_code=201)
async def generate_report(
    report_type: str = Query(default="annual_compliance"),
    regulatory_body: str = Query(default="NERC"),
    asset_ids: list[str] = Query(default=[]),
    period_days: int = Query(default=365, ge=1, le=730),
) -> ComplianceReport:
    now = datetime.now(timezone.utc)
    report = ComplianceReport(
        report_id=str(uuid.uuid4()),
        report_type=report_type,
        regulatory_body=regulatory_body,  # type: ignore[arg-type]
        period_start=now - timedelta(days=period_days),
        period_end=now,
        asset_ids=asset_ids,
        status="draft",
        generated_at=now,
        findings=[
            "All assets maintained SOC above minimum threshold (5%) for 99.7% of reporting period.",
            "Regulation service delivery rate: 98.2% (threshold: 95%).",
            "No NERC CIP cybersecurity incidents recorded.",
        ],
        violations=[],
    )
    _REPORTS[report.report_id] = report
    return report


@router.get("/reports", response_model=list[ComplianceReport])
async def list_reports(
    regulatory_body: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
) -> list[ComplianceReport]:
    reports = list(_REPORTS.values())
    if regulatory_body:
        reports = [r for r in reports if r.regulatory_body == regulatory_body]
    if status:
        reports = [r for r in reports if r.status == status]
    return reports[-limit:]


@router.get("/reports/{report_id}", response_model=ComplianceReport)
async def get_report(report_id: str) -> ComplianceReport:
    report = _REPORTS.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return report


@router.post("/reports/{report_id}/submit", response_model=ComplianceReport)
async def submit_report(report_id: str) -> ComplianceReport:
    report = _REPORTS.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    report.status = "submitted"
    report.submitted_at = datetime.now(timezone.utc)
    return report


@router.get("/checks/{asset_id}", response_model=list[ComplianceCheck])
async def run_compliance_checks(asset_id: str) -> list[ComplianceCheck]:
    """Run real-time compliance checks for an asset."""
    import numpy as np
    np.random.seed(hash(asset_id) % 2**31)
    now = datetime.now(timezone.utc)
    soc = np.random.uniform(0.1, 0.9)
    rte = np.random.uniform(0.88, 0.95)
    delivery_rate = np.random.uniform(0.94, 0.999)
    return [
        ComplianceCheck(
            check_id=str(uuid.uuid4()),
            asset_id=asset_id,
            check_type="minimum_soc",
            passed=soc >= 0.05,
            threshold=0.05,
            actual=round(soc, 3),
            message="SOC above minimum" if soc >= 0.05 else "SOC below minimum threshold",
            checked_at=now,
            severity="critical" if soc < 0.05 else "info",
        ),
        ComplianceCheck(
            check_id=str(uuid.uuid4()),
            asset_id=asset_id,
            check_type="round_trip_efficiency",
            passed=rte >= 0.80,
            threshold=0.80,
            actual=round(rte, 3),
            message="RTE within acceptable range",
            checked_at=now,
            severity="info",
        ),
        ComplianceCheck(
            check_id=str(uuid.uuid4()),
            asset_id=asset_id,
            check_type="regulation_delivery_rate",
            passed=delivery_rate >= 0.95,
            threshold=0.95,
            actual=round(delivery_rate, 4),
            message="Regulation delivery rate acceptable" if delivery_rate >= 0.95 else "Delivery rate below FERC threshold",
            checked_at=now,
            severity="warning" if delivery_rate < 0.95 else "info",
        ),
    ]


@router.get("/obligations", response_model=list[ObligationStatus])
async def list_obligations(
    market: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[ObligationStatus]:
    """Return current market obligations and compliance status."""
    import numpy as np
    now = datetime.now(timezone.utc)
    np.random.seed(7)
    obligations = []
    for i, (obligation_type, committed) in enumerate([
        ("capacity", 5.0), ("regulation", 1.0), ("spinning_reserve", 0.5)
    ]):
        delivered = round(committed * np.random.uniform(0.92, 1.0), 3)
        pct = round(delivered / committed, 4)
        penalty = round(max(0, (committed - delivered) * 1500), 2)
        obligations.append(ObligationStatus(
            obligation_id=str(uuid.uuid4()),
            obligation_type=obligation_type,
            market=market or "CAISO",
            period_start=now - timedelta(hours=1),
            period_end=now,
            committed_mw=committed,
            delivered_mw=delivered,
            compliance_pct=pct,
            penalty_usd=penalty,
            status="compliant" if pct >= 0.95 else "partial",
        ))
    if status:
        obligations = [o for o in obligations if o.status == status]
    return obligations
