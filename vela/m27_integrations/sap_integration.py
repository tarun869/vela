"""
SAP ERP integration for VPP financial and asset management.

Synchronizes asset master data, maintenance orders, cost centers,
and financial postings between Vela and SAP S/4HANA.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import time


@dataclass
class SAPAsset:
    asset_number: str
    description: str
    asset_class: str
    cost_center: str
    useful_life_years: int
    acquisition_cost_usd: float
    book_value_usd: float
    depreciation_method: str = "straight_line"


@dataclass
class SAPMaintenanceOrder:
    order_number: str
    asset_number: str
    description: str
    order_type: str      # "PM01" = preventive, "PM02" = corrective
    planned_date: str
    actual_date: Optional[str]
    planned_cost_usd: float
    actual_cost_usd: float = 0.0
    status: str = "created"    # created, released, completed, closed


@dataclass
class SAPCostPosting:
    document_number: str
    cost_center: str
    gl_account: str
    amount_usd: float
    posting_date: str
    text: str


class SAPIntegration:
    """
    SAP integration layer using RFC/BAPI calls (simulated in this implementation).

    In production: uses pyrfc or SAP REST APIs (Business Accelerator Hub).
    """

    def __init__(self, system_id: str = "SBX", client: str = "100") -> None:
        self.system_id = system_id
        self.client = client
        self._assets: Dict[str, SAPAsset] = {}
        self._orders: Dict[str, SAPMaintenanceOrder] = {}
        self._postings: List[SAPCostPosting] = []

    def create_asset(self, asset: SAPAsset) -> str:
        self._assets[asset.asset_number] = asset
        return asset.asset_number

    def get_asset(self, asset_number: str) -> Optional[SAPAsset]:
        return self._assets.get(asset_number)

    def create_maintenance_order(self, order: SAPMaintenanceOrder) -> str:
        self._orders[order.order_number] = order
        return order.order_number

    def complete_order(self, order_number: str, actual_cost_usd: float) -> bool:
        if order_number in self._orders:
            self._orders[order_number].status = "completed"
            self._orders[order_number].actual_cost_usd = actual_cost_usd
            return True
        return False

    def post_costs(self, posting: SAPCostPosting) -> str:
        self._postings.append(posting)
        return posting.document_number

    def calculate_depreciation(
        self,
        asset_number: str,
        years_elapsed: float,
    ) -> float:
        """Compute annual depreciation charge (straight-line)."""
        asset = self._assets.get(asset_number)
        if not asset:
            return 0.0
        return asset.acquisition_cost_usd / max(asset.useful_life_years, 1)

    def asset_register(self) -> List[Dict]:
        return [
            {
                "asset_number": a.asset_number,
                "description": a.description,
                "book_value_usd": a.book_value_usd,
                "cost_center": a.cost_center,
            }
            for a in self._assets.values()
        ]
