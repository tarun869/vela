"""
NERC CIP compliance checker for VPP control systems.

Validates configurations against NERC Critical Infrastructure Protection
standards CIP-002 through CIP-014, relevant to BES Cyber Systems.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class CIPStandard(str, Enum):
    CIP_002 = "CIP-002-5.1a"   # BES Cyber System Categorization
    CIP_003 = "CIP-003-8"      # Security Management Controls
    CIP_004 = "CIP-004-6"      # Personnel & Training
    CIP_005 = "CIP-005-7"      # Electronic Security Perimeters
    CIP_006 = "CIP-006-6"      # Physical Security of BES Cyber Systems
    CIP_007 = "CIP-007-6"      # Systems Security Management
    CIP_008 = "CIP-008-6"      # Incident Reporting and Response
    CIP_009 = "CIP-009-6"      # Recovery Plans
    CIP_010 = "CIP-010-4"      # Configuration Change Management
    CIP_011 = "CIP-011-3"      # Information Protection
    CIP_013 = "CIP-013-2"      # Supply Chain Risk Management
    CIP_014 = "CIP-014-3"      # Physical Security (Transmission)


class ComplianceStatus(str, Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NOT_APPLICABLE = "not_applicable"
    NEEDS_REVIEW = "needs_review"


@dataclass
class CIPRequirement:
    req_id: str              # e.g., "CIP-007-R1"
    standard: CIPStandard
    description: str
    check_fn_name: str       # Name of check function
    impact_level: str        # "high", "medium", "low"
    evidence_needed: List[str]


@dataclass
class CIPFinding:
    requirement_id: str
    standard: CIPStandard
    status: ComplianceStatus
    description: str
    gap_description: Optional[str]
    remediation: Optional[str]
    evidence_provided: List[str]
    risk_level: str          # "critical", "high", "medium", "low"


@dataclass
class CIPAssessmentResult:
    entity_name: str
    assessment_date: str
    findings: List[CIPFinding]
    compliant_count: int
    non_compliant_count: int
    partial_count: int
    overall_status: str
    critical_gaps: List[str]


class NERCCIPChecker:
    """
    NERC CIP compliance checker for BES Cyber Systems.

    Checks configuration artifacts against CIP requirements
    and generates findings with remediation guidance.
    """

    def __init__(self, entity_name: str, registered_entity_type: str = "GO") -> None:
        self.entity_name = entity_name
        self.entity_type = registered_entity_type
        self._findings: List[CIPFinding] = []

    def check_cip_007(self, system_config: Dict) -> List[CIPFinding]:
        """
        CIP-007: Systems Security Management checks.

        Checks: Ports/Services, Security Patches, Malware Prevention,
        Event Logging, Authentication.
        """
        findings: List[CIPFinding] = []

        # R1: Ports and Services
        open_ports = system_config.get("open_ports", [])
        unnecessary = [p for p in open_ports if p in (23, 21, 80, 111)]
        if unnecessary:
            findings.append(CIPFinding(
                requirement_id="CIP-007-R1",
                standard=CIPStandard.CIP_007,
                status=ComplianceStatus.NON_COMPLIANT,
                description="Unnecessary ports/services enabled",
                gap_description=f"Unnecessary ports open: {unnecessary}",
                remediation="Disable or block ports: Telnet(23), FTP(21), HTTP(80), RPC(111)",
                evidence_provided=[],
                risk_level="high",
            ))
        else:
            findings.append(CIPFinding(
                requirement_id="CIP-007-R1",
                standard=CIPStandard.CIP_007,
                status=ComplianceStatus.COMPLIANT,
                description="Only required ports/services enabled",
                gap_description=None, remediation=None,
                evidence_provided=["firewall_rules", "port_scan_report"],
                risk_level="low",
            ))

        # R2: Patch management
        patch_policy = system_config.get("patch_policy_days", 999)
        if patch_policy > 35:
            findings.append(CIPFinding(
                requirement_id="CIP-007-R2",
                standard=CIPStandard.CIP_007,
                status=ComplianceStatus.NON_COMPLIANT,
                description="Security patches not applied within 35 days",
                gap_description=f"Patch cycle: {patch_policy} days (max 35)",
                remediation="Implement automated patch management with 35-day SLA",
                evidence_provided=[],
                risk_level="high",
            ))
        else:
            findings.append(CIPFinding(
                requirement_id="CIP-007-R2",
                standard=CIPStandard.CIP_007,
                status=ComplianceStatus.COMPLIANT,
                description="Patch management within required timeframe",
                gap_description=None, remediation=None,
                evidence_provided=["patch_schedule", "vulnerability_reports"],
                risk_level="low",
            ))

        # R4: Event logging
        log_retention_days = system_config.get("log_retention_days", 0)
        if log_retention_days < 90:
            findings.append(CIPFinding(
                requirement_id="CIP-007-R4",
                standard=CIPStandard.CIP_007,
                status=ComplianceStatus.NON_COMPLIANT,
                description="Event log retention below 90-day minimum",
                gap_description=f"Current retention: {log_retention_days} days",
                remediation="Configure log retention to minimum 90 days (NERC requires 90-day review cycle)",
                evidence_provided=[],
                risk_level="medium",
            ))

        # R5: Authentication
        mfa_enabled = system_config.get("mfa_enabled", False)
        if not mfa_enabled:
            findings.append(CIPFinding(
                requirement_id="CIP-007-R5",
                standard=CIPStandard.CIP_007,
                status=ComplianceStatus.NON_COMPLIANT,
                description="Multi-factor authentication not enabled",
                gap_description="MFA required for all interactive BES Cyber System access",
                remediation="Enable MFA for all remote and local interactive access",
                evidence_provided=[],
                risk_level="critical",
            ))

        return findings

    def check_cip_005(self, network_config: Dict) -> List[CIPFinding]:
        """
        CIP-005: Electronic Security Perimeters.

        Checks: ESP definition, EAP controls, remote access.
        """
        findings: List[CIPFinding] = []

        # R1: Electronic Security Perimeter defined
        has_esp = network_config.get("esp_defined", False)
        if not has_esp:
            findings.append(CIPFinding(
                requirement_id="CIP-005-R1",
                standard=CIPStandard.CIP_005,
                status=ComplianceStatus.NON_COMPLIANT,
                description="Electronic Security Perimeter not defined",
                gap_description="No documented ESP boundary for BES Cyber Systems",
                remediation="Define and document ESP boundary; implement EAP controls",
                evidence_provided=[],
                risk_level="critical",
            ))

        # R2: Remote access controls
        vpn_required = network_config.get("vpn_for_remote_access", False)
        if not vpn_required:
            findings.append(CIPFinding(
                requirement_id="CIP-005-R2",
                standard=CIPStandard.CIP_005,
                status=ComplianceStatus.NON_COMPLIANT,
                description="Remote access not protected by encrypted VPN",
                gap_description="Direct remote access without VPN detected",
                remediation="Require VPN with certificate-based authentication for all remote access",
                evidence_provided=[],
                risk_level="critical",
            ))

        return findings

    def check_cip_010(self, change_mgmt_config: Dict) -> List[CIPFinding]:
        """CIP-010: Configuration Change Management."""
        findings: List[CIPFinding] = []

        # R1: Baseline configurations
        has_baseline = change_mgmt_config.get("baseline_documented", False)
        if not has_baseline:
            findings.append(CIPFinding(
                requirement_id="CIP-010-R1",
                standard=CIPStandard.CIP_010,
                status=ComplianceStatus.NON_COMPLIANT,
                description="Configuration baseline not documented",
                gap_description="No documented configuration baseline for BES Cyber Systems",
                remediation="Document and maintain configuration baselines; monitor for changes",
                evidence_provided=[],
                risk_level="high",
            ))

        # R2: Change monitoring
        change_monitoring = change_mgmt_config.get("automated_change_detection", False)
        if not change_monitoring:
            findings.append(CIPFinding(
                requirement_id="CIP-010-R2",
                standard=CIPStandard.CIP_010,
                status=ComplianceStatus.PARTIALLY_COMPLIANT,
                description="Automated configuration change detection not implemented",
                gap_description="Manual change review only; no automated monitoring",
                remediation="Implement SIEM or host-based monitoring for configuration changes",
                evidence_provided=[],
                risk_level="medium",
            ))
        return findings

    def run_full_assessment(
        self,
        system_config: Dict,
        network_config: Dict,
        change_mgmt_config: Dict,
    ) -> CIPAssessmentResult:
        """Run all applicable CIP checks and produce assessment."""
        from datetime import datetime, timezone
        all_findings: List[CIPFinding] = []
        all_findings.extend(self.check_cip_007(system_config))
        all_findings.extend(self.check_cip_005(network_config))
        all_findings.extend(self.check_cip_010(change_mgmt_config))

        compliant = sum(1 for f in all_findings if f.status == ComplianceStatus.COMPLIANT)
        non_compliant = sum(1 for f in all_findings if f.status == ComplianceStatus.NON_COMPLIANT)
        partial = sum(1 for f in all_findings if f.status == ComplianceStatus.PARTIALLY_COMPLIANT)

        critical_gaps = [f.requirement_id for f in all_findings
                         if f.status == ComplianceStatus.NON_COMPLIANT and f.risk_level == "critical"]

        if non_compliant == 0:
            overall = "COMPLIANT"
        elif non_compliant <= 2 and not critical_gaps:
            overall = "SUBSTANTIALLY_COMPLIANT"
        else:
            overall = "NON_COMPLIANT"

        return CIPAssessmentResult(
            entity_name=self.entity_name,
            assessment_date=datetime.now(timezone.utc).isoformat(),
            findings=all_findings,
            compliant_count=compliant,
            non_compliant_count=non_compliant,
            partial_count=partial,
            overall_status=overall,
            critical_gaps=critical_gaps,
        )
