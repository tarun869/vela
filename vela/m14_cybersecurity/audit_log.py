"""
Security audit logging for the Vela VPP platform.

Provides tamper-evident, structured audit records for all security-relevant
events including authentication, authorization, command dispatch, and
configuration changes. Compatible with NERC CIP-007 logging requirements.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class AuditEventType(str, Enum):
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    LOGOUT = "logout"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    DISPATCH_COMMAND = "dispatch_command"
    CONFIG_CHANGE = "config_change"
    DATA_ACCESS = "data_access"
    ANOMALY_DETECTED = "anomaly_detected"
    INTRUSION_DETECTED = "intrusion_detected"
    KEY_ROTATION = "key_rotation"
    POLICY_VIOLATION = "policy_violation"
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"


class AuditSeverity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AuditRecord:
    event_id: str
    event_type: AuditEventType
    severity: AuditSeverity
    timestamp_utc: str
    user_id: Optional[str]
    source_ip: Optional[str]
    resource_id: Optional[str]
    action: str
    outcome: str           # "success", "failure", "blocked"
    details: Dict[str, Any]
    previous_hash: str     # Hash of previous record (chaining)
    record_hash: str = ""  # Computed after creation

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of this record for tamper detection."""
        record_dict = {
            k: v for k, v in asdict(self).items() if k != "record_hash"
        }
        canonical = json.dumps(record_dict, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()


class AuditLog:
    """
    Append-only, hash-chained audit log for security events.

    Records are chained via hash pointers to detect tampering.
    Supports in-memory and file-based backends.
    """

    def __init__(
        self,
        log_file: Optional[str] = None,
        min_severity: AuditSeverity = AuditSeverity.INFO,
    ) -> None:
        self._records: List[AuditRecord] = []
        self._log_file = log_file
        self._min_severity = min_severity
        self._last_hash: str = "0" * 64   # Genesis hash
        self._python_logger = logging.getLogger("vela.audit")

        # Write genesis entry
        self._write_genesis()

    def _severity_level(self, sev: AuditSeverity) -> int:
        return {"debug": 0, "info": 1, "warning": 2, "critical": 3}[sev.value]

    def _should_log(self, severity: AuditSeverity) -> bool:
        return self._severity_level(severity) >= self._severity_level(self._min_severity)

    def _write_genesis(self) -> None:
        self.log(
            event_type=AuditEventType.SYSTEM_START,
            severity=AuditSeverity.INFO,
            action="audit_log_initialized",
            outcome="success",
            details={"genesis": True},
        )

    def log(
        self,
        event_type: AuditEventType,
        severity: AuditSeverity,
        action: str,
        outcome: str = "success",
        user_id: Optional[str] = None,
        source_ip: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditRecord:
        """
        Create and store an audit record.

        Returns:
            The created AuditRecord.
        """
        if not self._should_log(severity):
            return None  # type: ignore

        record = AuditRecord(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            severity=severity,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            source_ip=source_ip,
            resource_id=resource_id,
            action=action,
            outcome=outcome,
            details=details or {},
            previous_hash=self._last_hash,
        )
        record.record_hash = record.compute_hash()
        self._last_hash = record.record_hash
        self._records.append(record)

        # Mirror to Python logger
        log_msg = f"[AUDIT] {event_type.value} | {action} | {outcome}"
        if severity == AuditSeverity.CRITICAL:
            self._python_logger.critical(log_msg)
        elif severity == AuditSeverity.WARNING:
            self._python_logger.warning(log_msg)
        else:
            self._python_logger.info(log_msg)

        if self._log_file:
            self._append_to_file(record)

        return record

    def _append_to_file(self, record: AuditRecord) -> None:
        """Append record to JSONL file."""
        try:
            with open(self._log_file, "a") as f:
                f.write(json.dumps(asdict(record), default=str) + "\n")
        except OSError as e:
            self._python_logger.error(f"Failed to write audit log: {e}")

    def verify_integrity(self) -> Tuple[bool, List[int]]:
        """
        Verify hash chain integrity.

        Returns:
            (is_valid, list_of_corrupted_indices)
        """
        from typing import Tuple
        corrupted: List[int] = []
        prev_hash = "0" * 64

        for i, record in enumerate(self._records):
            if record.previous_hash != prev_hash:
                corrupted.append(i)
            expected_hash = record.compute_hash()
            if record.record_hash != expected_hash:
                corrupted.append(i)
            prev_hash = record.record_hash

        return len(corrupted) == 0, corrupted

    def query(
        self,
        event_type: Optional[AuditEventType] = None,
        user_id: Optional[str] = None,
        severity: Optional[AuditSeverity] = None,
        since: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[AuditRecord]:
        """Query audit records with optional filters."""
        results = self._records
        if event_type:
            results = [r for r in results if r.event_type == event_type]
        if user_id:
            results = [r for r in results if r.user_id == user_id]
        if severity:
            results = [r for r in results if r.severity == severity]
        if since:
            since_iso = since.isoformat()
            results = [r for r in results if r.timestamp_utc >= since_iso]
        return results[-limit:]

    def failed_auth_attempts(self, window_minutes: int = 15) -> Dict[str, int]:
        """Count failed authentication attempts per IP in the last N minutes."""
        cutoff = time.time() - window_minutes * 60
        counts: Dict[str, int] = {}
        for r in self._records:
            if r.event_type == AuditEventType.AUTH_FAILURE and r.source_ip:
                ts = datetime.fromisoformat(r.timestamp_utc).timestamp()
                if ts >= cutoff:
                    counts[r.source_ip] = counts.get(r.source_ip, 0) + 1
        return counts

    def critical_events_summary(self) -> Dict[str, int]:
        """Count critical events by type."""
        counts: Dict[str, int] = {}
        for r in self._records:
            if r.severity == AuditSeverity.CRITICAL:
                counts[r.event_type.value] = counts.get(r.event_type.value, 0) + 1
        return counts
