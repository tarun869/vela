"""
Automated report generation for VPP operations and management.

Generates structured reports (JSON, CSV, plain text) for:
  - Daily operational summaries
  - Monthly revenue reports
  - Compliance status reports
  - Executive dashboards
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json
import csv
import io


@dataclass
class ReportSection:
    title: str
    content: Any
    format_hint: str = "text"  # "text", "table", "chart_data", "kv"


@dataclass
class Report:
    report_id: str
    report_type: str
    generated_at: str
    period: str
    entity: str
    sections: List[ReportSection]
    metadata: Dict[str, Any] = field(default_factory=dict)


class ReportGenerator:
    """
    Automated report generator for VPP operations.
    """

    def __init__(self, entity_name: str) -> None:
        self.entity = entity_name

    def _new_id(self) -> str:
        import uuid
        return str(uuid.uuid4())[:8]

    def daily_ops_report(
        self,
        date: str,
        dispatch_summary: Dict[str, float],
        revenue_summary: Dict[str, float],
        asset_status: Dict[str, str],
        alerts: List[str],
    ) -> Report:
        """Generate daily operations report."""
        sections = [
            ReportSection(
                title="Dispatch Summary",
                content=dispatch_summary,
                format_hint="kv",
            ),
            ReportSection(
                title="Revenue Summary",
                content=revenue_summary,
                format_hint="kv",
            ),
            ReportSection(
                title="Asset Status",
                content=asset_status,
                format_hint="table",
            ),
            ReportSection(
                title="Alerts and Notifications",
                content=alerts,
                format_hint="text",
            ),
        ]
        return Report(
            report_id=self._new_id(),
            report_type="daily_ops",
            generated_at=datetime.now(timezone.utc).isoformat(),
            period=date,
            entity=self.entity,
            sections=sections,
        )

    def monthly_revenue_report(
        self,
        month: str,
        revenue_by_service: Dict[str, float],
        revenue_by_asset: Dict[str, float],
        benchmark_comparison: Dict[str, float],
    ) -> Report:
        """Generate monthly revenue attribution report."""
        total_revenue = sum(revenue_by_service.values())
        sections = [
            ReportSection(
                title="Revenue by Service",
                content={"data": revenue_by_service, "total": total_revenue},
                format_hint="chart_data",
            ),
            ReportSection(
                title="Revenue by Asset",
                content=revenue_by_asset,
                format_hint="table",
            ),
            ReportSection(
                title="Benchmark Comparison",
                content=benchmark_comparison,
                format_hint="kv",
            ),
        ]
        return Report(
            report_id=self._new_id(),
            report_type="monthly_revenue",
            generated_at=datetime.now(timezone.utc).isoformat(),
            period=month,
            entity=self.entity,
            sections=sections,
            metadata={"total_revenue_usd": total_revenue},
        )

    def to_json(self, report: Report) -> str:
        """Serialize report to JSON."""
        return json.dumps({
            "report_id": report.report_id,
            "report_type": report.report_type,
            "generated_at": report.generated_at,
            "period": report.period,
            "entity": report.entity,
            "sections": [
                {"title": s.title, "content": s.content, "format": s.format_hint}
                for s in report.sections
            ],
            "metadata": report.metadata,
        }, indent=2, default=str)

    def to_text_summary(self, report: Report) -> str:
        """Generate human-readable text summary."""
        lines = [
            f"{'='*60}",
            f"REPORT: {report.report_type.upper()}",
            f"Entity: {report.entity}",
            f"Period: {report.period}",
            f"Generated: {report.generated_at}",
            f"{'='*60}",
            "",
        ]
        for section in report.sections:
            lines.append(f"--- {section.title} ---")
            if isinstance(section.content, dict):
                for k, v in section.content.items():
                    lines.append(f"  {k}: {v}")
            elif isinstance(section.content, list):
                for item in section.content:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"  {section.content}")
            lines.append("")
        return "\n".join(lines)
