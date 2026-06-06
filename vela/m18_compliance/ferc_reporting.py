"""
FERC reporting utilities for VPP market participants.

Generates standardized reports required by the Federal Energy
Regulatory Commission for wholesale market participants including
market-based rate (MBR) filings, EQR (Electric Quarterly Reports),
and Order 2222 compliance documentation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import csv
import io


@dataclass
class EQRTransaction:
    """Electric Quarterly Report transaction record."""
    seller_id: str
    seller_name: str
    buyer_id: str
    buyer_name: str
    transaction_unique_id: str
    contract_type: str          # "C" for contract, "T" for tariff
    transaction_begin: str      # ISO datetime
    transaction_end: str
    time_zone: str
    point_of_delivery_balancing_authority: str
    point_of_receipt_balancing_authority: str
    class_name: str             # "firm", "non-firm"
    term_name: str              # "spot", "hour", "day", "week", "month", "year"
    increment_name: str         # "annual", "monthly", "daily", "hourly"
    increment_peaking_name: str  # "flat", "peak", "off-peak"
    product_name: str           # "capacity", "energy", "reserves"
    quantity_mw: float
    price_per_mwh: float
    total_transaction_value_usd: float


@dataclass
class MBRFiling:
    """Market-Based Rate filing components."""
    applicant_name: str
    docket_number: Optional[str]
    filing_type: str   # "initial", "triennial_update", "amendment"
    filing_date: str
    affiliate_list: List[str]
    generation_capacity_mw: float
    relevant_geographic_market: str
    market_power_analysis: Dict[str, float]  # metric -> value
    mitigation_measures: List[str]


@dataclass
class FERCReport:
    report_type: str
    period_start: str
    period_end: str
    filer_id: str
    filer_name: str
    content: str    # CSV or XML content
    submission_status: str  # "draft", "ready", "submitted"


class FERCReporter:
    """
    Generates FERC-compliant reports and filings.
    """

    def __init__(self, entity_id: str, entity_name: str) -> None:
        self.entity_id = entity_id
        self.entity_name = entity_name

    def generate_eqr(
        self,
        transactions: List[EQRTransaction],
        quarter: str,    # "Q1", "Q2", "Q3", "Q4"
        year: int,
    ) -> FERCReport:
        """
        Generate Electric Quarterly Report (EQR) CSV.

        EQR is filed within 30 days after each quarter end.
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Header per FERC EQR specification
        writer.writerow([
            "Seller_ID", "Seller_Name", "Buyer_ID", "Buyer_Name",
            "Transaction_Unique_ID", "Contract_Type", "Transaction_Begin",
            "Transaction_End", "Time_Zone", "POD_BA", "POR_BA",
            "Class", "Term", "Increment", "Increment_Peaking",
            "Product", "Quantity_MW", "Price_MWh", "Total_Value_USD"
        ])

        for txn in transactions:
            writer.writerow([
                txn.seller_id, txn.seller_name, txn.buyer_id, txn.buyer_name,
                txn.transaction_unique_id, txn.contract_type,
                txn.transaction_begin, txn.transaction_end, txn.time_zone,
                txn.point_of_delivery_balancing_authority,
                txn.point_of_receipt_balancing_authority,
                txn.class_name, txn.term_name, txn.increment_name,
                txn.increment_peaking_name, txn.product_name,
                f"{txn.quantity_mw:.3f}", f"{txn.price_per_mwh:.4f}",
                f"{txn.total_transaction_value_usd:.2f}"
            ])

        quarter_months = {"Q1": "01-31", "Q2": "04-30", "Q3": "07-31", "Q4": "10-31"}
        period_end = f"{year}-{quarter_months.get(quarter, '12-31')}"

        return FERCReport(
            report_type="EQR",
            period_start=f"{year}-01-01",
            period_end=period_end,
            filer_id=self.entity_id,
            filer_name=self.entity_name,
            content=output.getvalue(),
            submission_status="draft",
        )

    def generate_order_2222_report(
        self,
        aggregated_resources: List[Dict],
        iso_rto: str,
    ) -> FERCReport:
        """
        Generate Order 2222 aggregated DER participation report.

        FERC Order 2222 requires ISOs/RTOs to allow DER aggregators
        to participate in all capacity, energy, and ancillary service markets.
        """
        lines = [
            f"FERC Order 2222 Aggregated DER Participation Report",
            f"Filer: {self.entity_name} ({self.entity_id})",
            f"ISO/RTO: {iso_rto}",
            f"Report Date: {datetime.now(timezone.utc).isoformat()}",
            "",
            "Resource Summary:",
        ]

        total_capacity = 0.0
        for res in aggregated_resources:
            lines.append(f"  {res.get('resource_id', 'N/A')}: "
                         f"{res.get('capacity_kw', 0)/1000:.2f} MW, "
                         f"Type: {res.get('type', 'unknown')}")
            total_capacity += res.get("capacity_kw", 0)

        lines.append(f"\nTotal Aggregated Capacity: {total_capacity/1000:.2f} MW")
        lines.append(f"Number of Resources: {len(aggregated_resources)}")

        return FERCReport(
            report_type="ORDER_2222",
            period_start=datetime.now(timezone.utc).date().isoformat(),
            period_end=datetime.now(timezone.utc).date().isoformat(),
            filer_id=self.entity_id,
            filer_name=self.entity_name,
            content="\n".join(lines),
            submission_status="draft",
        )

    def market_power_screen(
        self,
        seller_capacity_mw: float,
        market_capacity_mw: float,
        hhi_index: float = 0.0,
    ) -> Dict[str, str]:
        """
        Apply FERC market power screens for MBR eligibility.

        Returns:
            Dict with screen results and pass/fail status.
        """
        results: Dict[str, str] = {}

        # 20% pivotal supplier test
        share = seller_capacity_mw / max(market_capacity_mw, 1.0)
        results["20pct_screen"] = "PASS" if share < 0.20 else "FAIL"
        results["market_share"] = f"{share*100:.1f}%"

        # HHI threshold (1800 for highly concentrated markets)
        results["hhi_screen"] = "PASS" if hhi_index < 1800 else "FAIL"
        results["hhi"] = f"{hhi_index:.0f}"

        # Pivot test: seller can raise prices by withdrawing capacity
        pivotal_threshold = 0.15
        results["pivotal_supplier"] = "PASS" if share < pivotal_threshold else "FAIL"
        results["overall"] = "PASS" if all(v == "PASS" for k, v in results.items() if k.endswith("_screen") or k == "pivotal_supplier") else "FAIL"

        return results
