"""
ISO/RTO market rules registry and compliance validation.

Tracks current market rules, tariff provisions, and FERC orders
applicable to VPP participation across ISOs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class MarketRule:
    rule_id: str
    iso: str
    title: str
    description: str
    effective_date: str
    category: str   # "eligibility", "offer", "settlement", "measurement", "compliance"
    url: str = ""
    vpp_relevant: bool = True


@dataclass
class RuleViolation:
    rule_id: str
    resource_id: str
    description: str
    severity: str    # "warning", "violation", "disqualification"


# Pre-populated key rules
MARKET_RULES_DB: Dict[str, List[MarketRule]] = {
    "ERCOT": [
        MarketRule("ERC-001", "ERCOT", "ERCOT Protocols §6.5 ESR Registration",
                   "Energy Storage Resources must register separately for each ancillary service",
                   "2023-01-01", "eligibility"),
        MarketRule("ERC-002", "ERCOT", "ERCOT Protocols §7.4 4CP Measurement",
                   "Coincident Peak demand measured at 15-min intervals during Jun–Sep",
                   "2022-06-01", "measurement"),
        MarketRule("ERC-003", "ERCOT", "ERCOT Protocols §6.8.1 ECRS",
                   "ERCOT Contingency Reserve Service — 10-min response, 30-min sustain",
                   "2023-05-01", "eligibility"),
    ],
    "CAISO": [
        MarketRule("CAI-001", "CAISO", "CAISO Tariff §29 Storage Participation",
                   "Storage resources participate as Pumped Hydro or Non-Generator Resource",
                   "2022-03-01", "eligibility"),
        MarketRule("CAI-002", "CAISO", "FERC Order 2222 DER Aggregation",
                   "DER aggregators must meet minimum 500 kW aggregate threshold",
                   "2022-08-01", "eligibility"),
    ],
    "PJM": [
        MarketRule("PJM-001", "PJM", "PJM Manual 10 Pre-Scheduling for Storage",
                   "Storage resources must submit self-schedule or bid for DA commitment",
                   "2021-12-01", "offer"),
        MarketRule("PJM-002", "PJM", "PJM Manual 11 Energy Market Offer Caps",
                   "Day-ahead offer cap: $2,000/MWh; Real-time: $2,000/MWh",
                   "2023-01-01", "offer"),
    ],
}


class MarketRulesEngine:
    """Validates VPP operations against ISO market rules."""

    def __init__(self) -> None:
        self._rules: Dict[str, MarketRule] = {}
        for iso_rules in MARKET_RULES_DB.values():
            for rule in iso_rules:
                self._rules[rule.rule_id] = rule

    def rules_for_iso(self, iso: str, category: Optional[str] = None) -> List[MarketRule]:
        rules = [r for r in self._rules.values() if r.iso == iso and r.vpp_relevant]
        if category:
            rules = [r for r in rules if r.category == category]
        return rules

    def check_offer_cap(self, iso: str, offer_price: float) -> Optional[RuleViolation]:
        """Check if offer price exceeds ISO cap."""
        caps = {"ERCOT": 5000.0, "CAISO": 2000.0, "PJM": 2000.0, "MISO": 3500.0}
        cap = caps.get(iso, 9999.0)
        if offer_price > cap:
            return RuleViolation(
                rule_id=f"{iso[:3].upper()}-PRICE-CAP",
                resource_id="",
                description=f"Offer {offer_price:.0f} $/MWh exceeds {iso} cap {cap:.0f} $/MWh",
                severity="violation",
            )
        return None

    def all_rule_ids(self) -> List[str]:
        return list(self._rules.keys())
