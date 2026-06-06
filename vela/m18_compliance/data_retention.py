"""
Data retention policy enforcement for VPP operational data.

Implements configurable data retention policies per NERC CIP,
FERC, ISO, and internal governance requirements.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple


class DataCategory(str, Enum):
    AUDIT_LOGS = "audit_logs"
    DISPATCH_RECORDS = "dispatch_records"
    MARKET_DATA = "market_data"
    TELEMETRY = "telemetry"
    SETTLEMENT_DATA = "settlement_data"
    COMPLIANCE_DOCS = "compliance_documents"
    CYBER_SECURITY = "cyber_security_logs"
    PERSONNEL = "personnel_records"
    CONTRACTS = "contracts"
    FINANCIAL = "financial_records"


@dataclass
class RetentionPolicy:
    category: DataCategory
    retention_days: int
    regulation_source: str     # "NERC-CIP-007", "FERC-EQR", "ERCOT", etc.
    delete_after_expiry: bool = False  # Auto-delete vs archive
    archive_location: str = "cold_storage"
    legal_hold_override: bool = False   # Legal hold suspends deletion
    encrypted_required: bool = True


# Default retention policies per regulatory requirements
DEFAULT_POLICIES: Dict[DataCategory, RetentionPolicy] = {
    DataCategory.AUDIT_LOGS: RetentionPolicy(
        DataCategory.AUDIT_LOGS, 365 * 3, "NERC-CIP-007-R4",  # 3 years
        delete_after_expiry=False, encrypted_required=True,
    ),
    DataCategory.DISPATCH_RECORDS: RetentionPolicy(
        DataCategory.DISPATCH_RECORDS, 365 * 5, "FERC-MBR",
        delete_after_expiry=False, encrypted_required=True,
    ),
    DataCategory.MARKET_DATA: RetentionPolicy(
        DataCategory.MARKET_DATA, 365 * 2, "ISO-ERCOT-PROTOCOLS",
        delete_after_expiry=False, encrypted_required=False,
    ),
    DataCategory.TELEMETRY: RetentionPolicy(
        DataCategory.TELEMETRY, 90, "NERC-CIP-007",
        delete_after_expiry=True, encrypted_required=False,
    ),
    DataCategory.SETTLEMENT_DATA: RetentionPolicy(
        DataCategory.SETTLEMENT_DATA, 365 * 7, "FERC-EQR",
        delete_after_expiry=False, encrypted_required=True,
    ),
    DataCategory.CYBER_SECURITY: RetentionPolicy(
        DataCategory.CYBER_SECURITY, 365 * 3, "NERC-CIP-007-R4",
        delete_after_expiry=False, encrypted_required=True,
    ),
    DataCategory.CONTRACTS: RetentionPolicy(
        DataCategory.CONTRACTS, 365 * 10, "LEGAL",
        delete_after_expiry=False, encrypted_required=True,
    ),
    DataCategory.FINANCIAL: RetentionPolicy(
        DataCategory.FINANCIAL, 365 * 7, "SOX",
        delete_after_expiry=False, encrypted_required=True,
    ),
}


@dataclass
class DataRecord:
    record_id: str
    category: DataCategory
    created_at: str
    size_bytes: int
    location: str
    encrypted: bool
    on_legal_hold: bool = False
    archived: bool = False
    deleted: bool = False


class DataRetentionManager:
    """
    Enforces data retention policies across VPP data stores.

    Scans records, identifies expired data, and executes
    deletion or archival per policy.
    """

    def __init__(self, policies: Optional[Dict[DataCategory, RetentionPolicy]] = None) -> None:
        self._policies = policies or DEFAULT_POLICIES
        self._records: Dict[str, DataRecord] = {}
        self._enforcement_log: List[Dict] = []

    def register_record(self, record: DataRecord) -> None:
        self._records[record.record_id] = record

    def get_policy(self, category: DataCategory) -> RetentionPolicy:
        return self._policies.get(category, RetentionPolicy(
            category, 365, "default", delete_after_expiry=False
        ))

    def is_expired(self, record: DataRecord) -> bool:
        """Check if a record has exceeded its retention period."""
        policy = self.get_policy(record.category)
        if record.on_legal_hold:
            return False  # Legal hold overrides expiry
        expiry = datetime.fromisoformat(record.created_at) + timedelta(days=policy.retention_days)
        return datetime.now(timezone.utc) > expiry

    def expiry_date(self, record: DataRecord) -> str:
        """Compute expiry date for a record."""
        policy = self.get_policy(record.category)
        expiry = datetime.fromisoformat(record.created_at) + timedelta(days=policy.retention_days)
        return expiry.isoformat()

    def enforce_policies(self, dry_run: bool = False) -> Dict[str, int]:
        """
        Scan all records and enforce retention policies.

        Args:
            dry_run: If True, report what would be done without acting.

        Returns:
            Summary counts: {archived, deleted, legal_hold, compliant}.
        """
        summary = {"archived": 0, "deleted": 0, "legal_hold": 0, "compliant": 0}
        now = datetime.now(timezone.utc).isoformat()

        for record_id, record in self._records.items():
            if record.deleted:
                continue
            if record.on_legal_hold:
                summary["legal_hold"] += 1
                continue

            if self.is_expired(record):
                policy = self.get_policy(record.category)
                action = "delete" if policy.delete_after_expiry else "archive"

                if not dry_run:
                    if action == "delete":
                        record.deleted = True
                        summary["deleted"] += 1
                    else:
                        record.archived = True
                        record.location = policy.archive_location
                        summary["archived"] += 1
                else:
                    summary[action + "d"] = summary.get(action + "d", 0) + 1

                self._enforcement_log.append({
                    "timestamp": now,
                    "record_id": record_id,
                    "category": record.category.value,
                    "action": action,
                    "dry_run": dry_run,
                })
            else:
                summary["compliant"] += 1

        return summary

    def place_legal_hold(self, record_ids: List[str], reason: str) -> int:
        """Place records under legal hold to prevent deletion."""
        count = 0
        for rid in record_ids:
            if rid in self._records:
                self._records[rid].on_legal_hold = True
                count += 1
        self._enforcement_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "legal_hold",
            "records": record_ids,
            "reason": reason,
        })
        return count

    def compliance_report(self) -> Dict[str, any]:
        """Generate data retention compliance summary."""
        by_category: Dict[str, Dict[str, int]] = {}
        for record in self._records.values():
            cat = record.category.value
            by_category.setdefault(cat, {"total": 0, "expired": 0, "compliant": 0, "archived": 0})
            by_category[cat]["total"] += 1
            if record.archived:
                by_category[cat]["archived"] += 1
            elif not record.deleted and not self.is_expired(record):
                by_category[cat]["compliant"] += 1
            elif self.is_expired(record) and not record.deleted:
                by_category[cat]["expired"] += 1

        return {
            "total_records": len(self._records),
            "by_category": by_category,
            "enforcement_actions": len(self._enforcement_log),
        }
