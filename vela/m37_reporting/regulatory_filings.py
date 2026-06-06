"""
Regulatory filing generator for VPP compliance submissions.

Produces FERC EQR, NERC CIP audit evidence, and ISO compliance
report packages in required formats.
"""
from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class EQRRecord:
    transaction_id: str
    seller_id: str
    buyer_id: str
    market: str
    transaction_date: str
    quantity_mwh: float
    price_usd_mwh: float
    settlement_point: str


@dataclass
class NERCEvidence:
    requirement_id: str    # CIP-007-R1, etc.
    description: str
    evidence_type: str     # "policy", "config", "log", "test_result"
    file_reference: str
    date_collected: str
    compliant: bool
    comments: str = ""


class RegulatoryFilingsGenerator:
    """
    Generates formatted regulatory submissions for FERC and NERC.
    """

    def ferc_eqr_csv(self, records: List[EQRRecord]) -> bytes:
        """
        Generate FERC Electric Quarterly Report CSV.

        Format per FERC EQR specification (18 CFR Part 35).
        """
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "Transaction ID", "Seller ID", "Buyer ID", "Market",
            "Transaction Date", "Quantity MWh", "Price $/MWh", "Settlement Point",
        ])
        for rec in records:
            writer.writerow([
                rec.transaction_id, rec.seller_id, rec.buyer_id,
                rec.market, rec.transaction_date,
                f"{rec.quantity_mwh:.4f}", f"{rec.price_usd_mwh:.4f}",
                rec.settlement_point,
            ])
        return buf.getvalue().encode("utf-8")

    def nerc_cip_evidence_package(self, evidence: List[NERCEvidence]) -> Dict[str, Any]:
        """
        Build NERC CIP audit evidence package.

        Returns structured dict suitable for serialization to JSON/XML
        for submission to regional entity (RE).
        """
        by_requirement: Dict[str, List[Dict]] = {}
        for ev in evidence:
            by_requirement.setdefault(ev.requirement_id, []).append({
                "description": ev.description,
                "evidence_type": ev.evidence_type,
                "file_reference": ev.file_reference,
                "date_collected": ev.date_collected,
                "compliant": ev.compliant,
                "comments": ev.comments,
            })

        compliant_count = sum(1 for e in evidence if e.compliant)
        gap_count = sum(1 for e in evidence if not e.compliant)

        return {
            "package_generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_requirements": len(by_requirement),
            "compliant_findings": compliant_count,
            "gap_findings": gap_count,
            "compliance_rate_pct": compliant_count / max(len(evidence), 1) * 100,
            "evidence_by_requirement": by_requirement,
        }

    def iso_performance_report(
        self,
        iso: str,
        start_date: str,
        end_date: str,
        performance_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build ISO performance report for ancillary service settlements."""
        total_events = len(performance_data)
        compliant = sum(1 for d in performance_data if d.get("compliant", False))
        total_mwh = sum(d.get("mwh_dispatched", 0.0) for d in performance_data)
        total_revenue = sum(d.get("revenue_usd", 0.0) for d in performance_data)

        return {
            "iso": iso,
            "reporting_period": {"start": start_date, "end": end_date},
            "total_events": total_events,
            "compliant_events": compliant,
            "compliance_rate_pct": compliant / max(total_events, 1) * 100,
            "total_mwh_dispatched": total_mwh,
            "total_revenue_usd": total_revenue,
            "avg_revenue_per_event_usd": total_revenue / max(total_events, 1),
        }
