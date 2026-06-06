"""
PDF report generator for VPP executive and regulatory reports.

Generates professional PDF documents using reportlab (if available)
or falls back to structured text output.
"""
from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class PDFSection:
    heading: str
    body_text: str
    table_data: Optional[List[List[str]]] = None   # Rows including header
    page_break_after: bool = False


class PDFReportGenerator:
    """
    Generates PDF reports for VPP management and regulatory submissions.

    Uses reportlab if installed; returns formatted text bytes otherwise.
    """

    def generate(
        self,
        title: str,
        subtitle: str,
        sections: List[PDFSection],
        footer_text: str = "Confidential — Vela VPP Platform",
    ) -> bytes:
        """Generate PDF document and return bytes."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib import colors
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Table, TableStyle,
                Spacer, PageBreak, HRFlowable
            )

            buf = io.BytesIO()
            doc = SimpleDocTemplate(buf, pagesize=letter,
                                    leftMargin=inch, rightMargin=inch,
                                    topMargin=inch, bottomMargin=inch)
            styles = getSampleStyleSheet()

            elements = []

            # Title
            title_style = ParagraphStyle("title", fontSize=20, spaceAfter=10, textColor=colors.HexColor("#1F4E79"))
            elements.append(Paragraph(title, title_style))
            elements.append(Paragraph(subtitle, styles["Normal"]))
            ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
            elements.append(Paragraph(f"Generated: {ts}", styles["Italic"]))
            elements.append(Spacer(1, 0.25 * inch))
            elements.append(HRFlowable(width="100%", thickness=1))
            elements.append(Spacer(1, 0.1 * inch))

            for section in sections:
                elements.append(Paragraph(section.heading, styles["Heading2"]))
                elements.append(Paragraph(section.body_text, styles["Normal"]))
                if section.table_data:
                    t = Table(section.table_data)
                    t.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]))
                    elements.append(t)
                elements.append(Spacer(1, 0.2 * inch))
                if section.page_break_after:
                    elements.append(PageBreak())

            doc.build(elements)
            return buf.getvalue()

        except ImportError:
            # Fallback: formatted text
            lines = [f"{title}\n{subtitle}\n{'='*60}\n"]
            for section in sections:
                lines.append(f"\n{section.heading}\n{'-'*40}")
                lines.append(section.body_text)
                if section.table_data:
                    for row in section.table_data:
                        lines.append("  |  ".join(str(c) for c in row))
            return "\n".join(lines).encode("utf-8")
