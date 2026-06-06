"""
Salesforce CRM integration for VPP customer and contract management.

Syncs VPP site data, enrollment status, and revenue data to/from
Salesforce using REST API with OAuth2 authentication.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SFAccount:
    account_id: str
    name: str
    industry: str
    annual_revenue: float
    billing_address: str
    vpp_enrolled: bool = False
    enrolled_capacity_mw: float = 0.0


@dataclass
class SFOpportunity:
    opp_id: str
    account_id: str
    name: str
    stage: str            # "Prospecting", "Qualification", "Closed Won", etc.
    amount_usd: float
    close_date: str
    product: str          # "Battery Storage", "Demand Response", "Solar+Storage"


class SalesforceClient:
    """
    Salesforce CRM integration with simulated REST API.

    In production, uses simple-salesforce library with JWT flow OAuth2.
    """

    def __init__(self, instance_url: str = "", access_token: str = "") -> None:
        self.instance_url = instance_url
        self.access_token = access_token
        self._accounts: Dict[str, SFAccount] = {}
        self._opportunities: Dict[str, SFOpportunity] = {}

    def upsert_account(self, account: SFAccount) -> str:
        """Create or update an Account record. Returns Salesforce ID."""
        self._accounts[account.account_id] = account
        return account.account_id

    def get_account(self, account_id: str) -> Optional[SFAccount]:
        return self._accounts.get(account_id)

    def create_opportunity(self, opp: SFOpportunity) -> str:
        self._opportunities[opp.opp_id] = opp
        return opp.opp_id

    def update_opportunity_stage(self, opp_id: str, stage: str) -> bool:
        if opp_id in self._opportunities:
            self._opportunities[opp_id].stage = stage
            return True
        return False

    def query_enrolled_accounts(self) -> List[SFAccount]:
        return [a for a in self._accounts.values() if a.vpp_enrolled]

    def sync_vpp_enrollment(
        self,
        account_id: str,
        enrolled: bool,
        capacity_mw: float,
    ) -> bool:
        """Sync VPP enrollment status from Vela to Salesforce."""
        if account_id in self._accounts:
            acc = self._accounts[account_id]
            acc.vpp_enrolled = enrolled
            acc.enrolled_capacity_mw = capacity_mw
            return True
        return False

    def pipeline_by_product(self) -> Dict[str, float]:
        """Summarize opportunity pipeline by product type."""
        result: Dict[str, float] = {}
        for opp in self._opportunities.values():
            if opp.stage not in ("Closed Lost",):
                result[opp.product] = result.get(opp.product, 0.0) + opp.amount_usd
        return result
