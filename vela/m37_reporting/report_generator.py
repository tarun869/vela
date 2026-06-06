"""
Report generator for VPP operational and financial reports.

Produces structured report objects for daily operations summaries,
monthly revenue reports, and regulatory filings.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ReportSection:
    title: str
    data: Dict[str, Any]
    narrative: str = ""


@dataclass
class Report:
    report_id: str
    report_type: str
    generated_at: float
    period: str
    sections: List[ReportSection] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class VPPReportGenerator:
    """
    Generates operational and financial reports for VPP systems.

    Composes report sections from data sources and produces
    structured output that can be rendered to JSON, HTML, or PDF.
    """

    def generate_daily_ops_report(
        self,
        date: str,
        dispatch_summary: Dict[str, Any],
        market_prices: Dict[str, float],
        asset_status: Dict[str, Any],
    ) -> Report:
        """Build daily operations summary report."""
        import uuid
        sections = [
            ReportSection(
                title="Dispatch Summary",
                data=dispatch_summary,
                narrative=(
                    f"Total dispatched {dispatch_summary.get('total_mwh', 0):.1f} MWh "
                    f"across {dispatch_summary.get('n_assets', 0)} assets."
                ),
            ),
            ReportSection(
                title="Market Prices",
                data=market_prices,
                narrative=(
                    f"Average LMP: ${market_prices.get('avg_lmp', 0):.2f}/MWh. "
                    f"Peak hour price: ${market_prices.get('peak_lmp', 0):.2f}/MWh."
                ),
            ),
            ReportSection(
                title="Asset Status",
                data=asset_status,
                narrative=(
                    f"{asset_status.get('online', 0)} assets online, "
                    f"{asset_status.get('faulted', 0)} with active faults."
                ),
            ),
        ]
        return Report(
            report_id=str(uuid.uuid4())[:8],
            report_type="daily_ops",
            generated_at=time.time(),
            period=date,
            sections=sections,
        )

    def generate_monthly_revenue_report(
        self,
        month: str,
        revenue_by_service: Dict[str, float],
        settlement_data: Dict[str, Any],
    ) -> Report:
        """Build monthly revenue report with service breakdown."""
        import uuid
        total = sum(revenue_by_service.values())
        sections = [
            ReportSection(
                title="Revenue by Service",
                data=revenue_by_service,
                narrative=(
                    f"Total revenue: ${total:,.2f}. "
                    f"Dominant service: {max(revenue_by_service, key=lambda k: revenue_by_service[k], default='N/A')}."
                ),
            ),
            ReportSection(
                title="Settlement",
                data=settlement_data,
                narrative=f"Settled {settlement_data.get('intervals_settled', 0)} 5-minute intervals.",
            ),
        ]
        return Report(
            report_id=str(uuid.uuid4())[:8],
            report_type="monthly_revenue",
            generated_at=time.time(),
            period=month,
            sections=sections,
            metadata={"total_revenue_usd": total},
        )

    def to_dict(self, report: Report) -> Dict[str, Any]:
        """Serialize report to nested dictionary."""
        return {
            "report_id": report.report_id,
            "report_type": report.report_type,
            "period": report.period,
            "generated_at": report.generated_at,
            "sections": [
                {"title": s.title, "data": s.data, "narrative": s.narrative}
                for s in report.sections
            ],
            "metadata": report.metadata,
        }

    def text_summary(self, report: Report) -> str:
        """Render report as plain text summary."""
        lines = [f"=== {report.report_type.upper()} — {report.period} ===\n"]
        for section in report.sections:
            lines.append(f"--- {section.title} ---")
            if section.narrative:
                lines.append(section.narrative)
            lines.append("")
        return "\n".join(lines)
