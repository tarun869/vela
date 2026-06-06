"""
Carbon credit and offset accounting for VPP fleet.

Tracks carbon credits generated from clean dispatch, manages
offset purchases, and maintains a carbon credit ledger.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple


class CreditType(str, Enum):
    GENERATED = "generated"       # Credits from clean generation
    PURCHASED = "purchased"       # Offsets bought from registry
    RETIRED = "retired"           # Credits surrendered for compliance
    TRANSFERRED = "transferred"   # Sold to third party


class OffsetQuality(str, Enum):
    GOLD_STANDARD = "gold_standard"
    VCS = "vcs"           # Verified Carbon Standard
    CAR = "car"           # Climate Action Reserve
    CDM = "cdm"           # Clean Development Mechanism
    REDD_PLUS = "redd_plus"


@dataclass
class CarbonCredit:
    credit_id: str
    credit_type: CreditType
    vintage_year: int
    quantity_tonnes: float       # tCO2e
    project_type: str            # "solar", "wind", "efficiency", "forestry"
    project_location: str
    registry: str
    serial_number: str
    created_at: str
    retired: bool = False
    retirement_date: Optional[str] = None
    compliance_use: Optional[str] = None   # Regulation/scheme it fulfills


@dataclass
class LedgerEntry:
    entry_id: str
    credit_id: str
    credit_type: CreditType
    quantity_tonnes: float
    price_usd_per_tonne: float
    total_value_usd: float
    timestamp: str
    counterparty: Optional[str]
    notes: str = ""


class CarbonCreditLedger:
    """
    Double-entry ledger for carbon credit tracking.

    Tracks:
      - Credits generated from VPP renewable dispatch
      - Purchased offsets
      - Retirements for compliance/voluntary goals
      - Transfers/sales
    """

    def __init__(self, entity_name: str) -> None:
        self.entity_name = entity_name
        self._credits: Dict[str, CarbonCredit] = {}
        self._ledger: List[LedgerEntry] = []

    def generate_credit(
        self,
        quantity_tonnes: float,
        vintage_year: int,
        project_type: str = "vpp_clean_dispatch",
        location: str = "USA",
        registry: str = "VCS",
    ) -> CarbonCredit:
        """
        Record a newly generated carbon credit from clean dispatch.
        """
        credit_id = str(uuid.uuid4())
        serial = f"VPP-{vintage_year}-{credit_id[:8].upper()}"
        now = datetime.now(timezone.utc).isoformat()

        credit = CarbonCredit(
            credit_id=credit_id,
            credit_type=CreditType.GENERATED,
            vintage_year=vintage_year,
            quantity_tonnes=quantity_tonnes,
            project_type=project_type,
            project_location=location,
            registry=registry,
            serial_number=serial,
            created_at=now,
        )
        self._credits[credit_id] = credit

        self._ledger.append(LedgerEntry(
            entry_id=str(uuid.uuid4()),
            credit_id=credit_id,
            credit_type=CreditType.GENERATED,
            quantity_tonnes=quantity_tonnes,
            price_usd_per_tonne=0.0,
            total_value_usd=0.0,
            timestamp=now,
            counterparty=None,
            notes=f"Generated from {project_type}",
        ))
        return credit

    def purchase_offsets(
        self,
        quantity_tonnes: float,
        price_per_tonne: float,
        registry: str,
        project_type: str,
        vintage_year: int,
        seller: str = "broker",
    ) -> CarbonCredit:
        """Record a carbon offset purchase."""
        credit_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        credit = CarbonCredit(
            credit_id=credit_id,
            credit_type=CreditType.PURCHASED,
            vintage_year=vintage_year,
            quantity_tonnes=quantity_tonnes,
            project_type=project_type,
            project_location="various",
            registry=registry,
            serial_number=f"PUR-{credit_id[:8].upper()}",
            created_at=now,
        )
        self._credits[credit_id] = credit

        self._ledger.append(LedgerEntry(
            entry_id=str(uuid.uuid4()),
            credit_id=credit_id,
            credit_type=CreditType.PURCHASED,
            quantity_tonnes=quantity_tonnes,
            price_usd_per_tonne=price_per_tonne,
            total_value_usd=quantity_tonnes * price_per_tonne,
            timestamp=now,
            counterparty=seller,
        ))
        return credit

    def retire_credit(
        self,
        credit_id: str,
        compliance_use: str = "voluntary_net_zero",
    ) -> bool:
        """Retire a credit for compliance or voluntary offsetting."""
        credit = self._credits.get(credit_id)
        if not credit or credit.retired:
            return False

        now = datetime.now(timezone.utc).isoformat()
        credit.retired = True
        credit.retirement_date = now
        credit.compliance_use = compliance_use

        self._ledger.append(LedgerEntry(
            entry_id=str(uuid.uuid4()),
            credit_id=credit_id,
            credit_type=CreditType.RETIRED,
            quantity_tonnes=credit.quantity_tonnes,
            price_usd_per_tonne=0.0,
            total_value_usd=0.0,
            timestamp=now,
            counterparty=None,
            notes=compliance_use,
        ))
        return True

    def net_position_tonnes(self) -> float:
        """Net carbon credit balance (generated + purchased - retired - transferred)."""
        generated = sum(e.quantity_tonnes for e in self._ledger if e.credit_type == CreditType.GENERATED)
        purchased = sum(e.quantity_tonnes for e in self._ledger if e.credit_type == CreditType.PURCHASED)
        retired = sum(e.quantity_tonnes for e in self._ledger if e.credit_type == CreditType.RETIRED)
        transferred = sum(e.quantity_tonnes for e in self._ledger if e.credit_type == CreditType.TRANSFERRED)
        return generated + purchased - retired - transferred

    def portfolio_value_usd(self, market_price_per_tonne: float = 25.0) -> float:
        """Mark-to-market value of unretired credit portfolio."""
        active = sum(
            c.quantity_tonnes for c in self._credits.values()
            if not c.retired and c.credit_type in (CreditType.GENERATED, CreditType.PURCHASED)
        )
        return active * market_price_per_tonne

    def annual_summary(self, year: int) -> Dict[str, float]:
        """Annual credits summary by type."""
        year_entries = [e for e in self._ledger if e.timestamp.startswith(str(year))]
        summary: Dict[str, float] = {}
        for entry in year_entries:
            key = entry.credit_type.value
            summary[key] = summary.get(key, 0.0) + entry.quantity_tonnes
        return summary
