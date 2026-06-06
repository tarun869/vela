"""
Compliance audit trail framework for regulatory inspections.

Maintains a structured, queryable audit trail for all compliance-related
activities, decisions, and evidence artifacts per NERC, FERC, and ISO requirements.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class AuditableEvent(str, Enum):
    COMPLIANCE_CHECK = "compliance_check"
    POLICY_UPDATE = "policy_update"
    EVIDENCE_SUBMITTED = "evidence_submitted"
    VIOLATION_IDENTIFIED = "violation_identified"
    REMEDIATION_COMPLETED = "remediation_completed"
    AUDIT_INITIATED = "audit_initiated"
    AUDIT_COMPLETED = "audit_completed"
    EXCEPTION_GRANTED = "exception_granted"
    TRAINING_COMPLETED = "training_completed"


@dataclass
class AuditEntry:
    entry_id: str
    event_type: AuditableEvent
    timestamp: str
    actor: str             # User or system that performed the action
    subject: str           # Resource or requirement being audited
    regulation: str        # "NERC-CIP", "FERC", "ISO-ERCOT", etc.
    description: str
    outcome: str           # "pass", "fail", "exception", "pending"
    evidence_refs: List[str]  # References to evidence documents
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComplianceObligation:
    obligation_id: str
    regulation: str
    requirement_ref: str    # e.g., "CIP-007-R2"
    description: str
    due_date: Optional[str]
    responsible_party: str
    status: str             # "open", "compliant", "non_compliant", "deferred"
    evidence_required: List[str]
    evidence_provided: List[str] = field(default_factory=list)
    last_verified: Optional[str] = None


class ComplianceAuditFramework:
    """
    Centralized compliance audit trail and obligation tracker.
    """

    def __init__(self, entity: str) -> None:
        self.entity = entity
        self._entries: List[AuditEntry] = []
        self._obligations: Dict[str, ComplianceObligation] = {}

    def record_event(
        self,
        event_type: AuditableEvent,
        actor: str,
        subject: str,
        regulation: str,
        description: str,
        outcome: str = "pass",
        evidence_refs: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            subject=subject,
            regulation=regulation,
            description=description,
            outcome=outcome,
            evidence_refs=evidence_refs or [],
            metadata=metadata or {},
        )
        self._entries.append(entry)
        return entry

    def register_obligation(self, obligation: ComplianceObligation) -> None:
        self._obligations[obligation.obligation_id] = obligation

    def update_obligation_status(
        self,
        obligation_id: str,
        new_status: str,
        evidence: Optional[List[str]] = None,
        actor: str = "system",
    ) -> bool:
        obl = self._obligations.get(obligation_id)
        if not obl:
            return False
        obl.status = new_status
        obl.last_verified = datetime.now(timezone.utc).isoformat()
        if evidence:
            obl.evidence_provided.extend(evidence)
        self.record_event(
            AuditableEvent.COMPLIANCE_CHECK,
            actor=actor,
            subject=obligation_id,
            regulation=obl.regulation,
            description=f"Obligation {obligation_id} status updated to {new_status}",
            outcome=new_status,
        )
        return True

    def open_obligations(self) -> List[ComplianceObligation]:
        return [o for o in self._obligations.values() if o.status in ("open", "non_compliant")]

    def overdue_obligations(self) -> List[ComplianceObligation]:
        now = datetime.now(timezone.utc).isoformat()
        return [
            o for o in self._obligations.values()
            if o.status == "open" and o.due_date and o.due_date < now
        ]

    def compliance_dashboard(self) -> Dict[str, Any]:
        total = len(self._obligations)
        compliant = sum(1 for o in self._obligations.values() if o.status == "compliant")
        non_compliant = sum(1 for o in self._obligations.values() if o.status == "non_compliant")
        overdue = len(self.overdue_obligations())

        return {
            "entity": self.entity,
            "total_obligations": total,
            "compliant": compliant,
            "non_compliant": non_compliant,
            "open": total - compliant - non_compliant,
            "overdue": overdue,
            "compliance_rate_pct": 100.0 * compliant / max(total, 1),
            "audit_entries": len(self._entries),
        }

    def export_audit_trail(self, regulation: Optional[str] = None) -> List[Dict]:
        entries = self._entries
        if regulation:
            entries = [e for e in entries if e.regulation == regulation]
        return [
            {
                "entry_id": e.entry_id, "event": e.event_type.value,
                "timestamp": e.timestamp, "actor": e.actor,
                "subject": e.subject, "regulation": e.regulation,
                "description": e.description, "outcome": e.outcome,
            }
            for e in entries
        ]
