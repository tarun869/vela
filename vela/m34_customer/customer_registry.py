"""
Customer registry for VPP enrolled sites and participant management.

Tracks enrolled customers, site configurations, program eligibility,
and historical performance for demand response and distributed generation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CustomerSegment(str, Enum):
    RESIDENTIAL = "residential"
    SMALL_COMMERCIAL = "small_commercial"
    MEDIUM_COMMERCIAL = "medium_commercial"
    LARGE_COMMERCIAL = "large_commercial"
    INDUSTRIAL = "industrial"
    UTILITY = "utility"


@dataclass
class Site:
    site_id: str
    customer_id: str
    address: str
    latitude: float
    longitude: float
    utility_account: str
    peak_demand_kw: float
    annual_energy_kwh: float
    segment: CustomerSegment
    dr_enrolled: bool = False
    vpp_enrolled: bool = False
    enrolled_programs: List[str] = field(default_factory=list)
    assets: List[str] = field(default_factory=list)   # asset_ids


@dataclass
class Customer:
    customer_id: str
    name: str
    email: str
    phone: str
    segment: CustomerSegment
    since_date: str
    account_manager: str
    sites: List[str] = field(default_factory=list)   # site_ids
    lifetime_value_usd: float = 0.0
    nps_score: Optional[int] = None   # Net Promoter Score (-100 to 100)


class CustomerRegistry:
    """
    Central registry for VPP customers and enrolled sites.

    Supports lookup by ID, segment filtering, and capacity aggregation.
    """

    def __init__(self) -> None:
        self._customers: Dict[str, Customer] = {}
        self._sites: Dict[str, Site] = {}

    def register_customer(self, customer: Customer) -> None:
        self._customers[customer.customer_id] = customer

    def register_site(self, site: Site) -> None:
        self._sites[site.site_id] = site
        if site.customer_id in self._customers:
            cust = self._customers[site.customer_id]
            if site.site_id not in cust.sites:
                cust.sites.append(site.site_id)

    def get_customer(self, customer_id: str) -> Optional[Customer]:
        return self._customers.get(customer_id)

    def get_site(self, site_id: str) -> Optional[Site]:
        return self._sites.get(site_id)

    def enrolled_sites(self, program_id: Optional[str] = None) -> List[Site]:
        if program_id:
            return [s for s in self._sites.values() if program_id in s.enrolled_programs]
        return [s for s in self._sites.values() if s.vpp_enrolled]

    def aggregate_capacity_kw(self, program_id: Optional[str] = None) -> float:
        return sum(s.peak_demand_kw for s in self.enrolled_sites(program_id))

    def customers_by_segment(self, segment: CustomerSegment) -> List[Customer]:
        return [c for c in self._customers.values() if c.segment == segment]

    def enroll(self, site_id: str, program_id: str) -> bool:
        site = self._sites.get(site_id)
        if not site:
            return False
        if program_id not in site.enrolled_programs:
            site.enrolled_programs.append(program_id)
        site.vpp_enrolled = True
        return True

    def unenroll(self, site_id: str, program_id: str) -> bool:
        site = self._sites.get(site_id)
        if not site:
            return False
        if program_id in site.enrolled_programs:
            site.enrolled_programs.remove(program_id)
        if not site.enrolled_programs:
            site.vpp_enrolled = False
        return True
