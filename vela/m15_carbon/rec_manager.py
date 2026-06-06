"""
Renewable Energy Certificate (REC) management.

Tracks generation of RECs from VPP renewable resources and manages
REC sales, retirements, and compliance with state RPS mandates.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple


class RECStatus(str, Enum):
    ACTIVE = "active"
    RETIRED = "retired"
    TRANSFERRED = "transferred"
    PENDING = "pending_registration"


class EnergySource(str, Enum):
    SOLAR = "solar"
    WIND = "wind"
    HYDRO = "hydro"
    GEOTHERMAL = "geothermal"
    BIOMASS = "biomass"
    FUEL_CELL = "fuel_cell"


@dataclass
class REC:
    rec_id: str
    serial_number: str
    energy_source: EnergySource
    capacity_mw: float
    energy_mwh: float            # 1 REC = 1 MWh of renewable generation
    generation_date: str
    facility_id: str
    facility_state: str
    status: RECStatus
    registry: str                # "WREGIS", "PJM-GATS", "NEPOOL-GIS", "ERCOT-PES"
    vintage_month: str           # YYYY-MM
    created_at: str
    retired_for: Optional[str] = None   # Compliance obligation or voluntary use
    sale_price_usd_mwh: Optional[float] = None


class RECManager:
    """
    Manages the full REC lifecycle from generation to retirement.

    Integrates with tracking systems (WREGIS, GATS, etc.) for VPP assets.
    """

    def __init__(self, registry: str = "WREGIS") -> None:
        self.registry = registry
        self._recs: Dict[str, REC] = {}
        self._generation_log: List[Dict] = []

    def register_generation(
        self,
        facility_id: str,
        energy_source: EnergySource,
        energy_mwh: float,
        capacity_mw: float,
        facility_state: str,
        generation_date: str,
    ) -> List[REC]:
        """
        Register renewable generation and issue RECs.

        1 MWh = 1 REC. Partial MWh are accumulated.

        Returns:
            List of REC objects created.
        """
        n_recs = int(energy_mwh)  # 1 REC per whole MWh
        remainder = energy_mwh - n_recs
        vintage = generation_date[:7]  # YYYY-MM
        now = datetime.now(timezone.utc).isoformat()

        recs: List[REC] = []
        for i in range(n_recs):
            rec_id = str(uuid.uuid4())
            serial = f"{self.registry}-{facility_state}-{facility_id[:8]}-{generation_date.replace('-', '')}-{i+1:04d}"
            rec = REC(
                rec_id=rec_id,
                serial_number=serial,
                energy_source=energy_source,
                capacity_mw=capacity_mw,
                energy_mwh=1.0,
                generation_date=generation_date,
                facility_id=facility_id,
                facility_state=facility_state,
                status=RECStatus.ACTIVE,
                registry=self.registry,
                vintage_month=vintage,
                created_at=now,
            )
            self._recs[rec_id] = rec
            recs.append(rec)

        self._generation_log.append({
            "facility_id": facility_id,
            "generation_date": generation_date,
            "energy_mwh": energy_mwh,
            "recs_issued": n_recs,
            "remainder_mwh": remainder,
        })
        return recs

    def retire_recs(
        self,
        rec_ids: List[str],
        purpose: str = "voluntary_renewable_claim",
    ) -> int:
        """
        Retire RECs for compliance or voluntary use.

        Returns:
            Number of RECs successfully retired.
        """
        retired = 0
        for rec_id in rec_ids:
            rec = self._recs.get(rec_id)
            if rec and rec.status == RECStatus.ACTIVE:
                rec.status = RECStatus.RETIRED
                rec.retired_for = purpose
                retired += 1
        return retired

    def sell_recs(
        self,
        rec_ids: List[str],
        buyer: str,
        price_usd_mwh: float,
    ) -> Tuple[int, float]:
        """
        Transfer RECs to buyer at given price.

        Returns:
            (recs_sold, total_proceeds_usd)
        """
        sold = 0
        proceeds = 0.0
        for rec_id in rec_ids:
            rec = self._recs.get(rec_id)
            if rec and rec.status == RECStatus.ACTIVE:
                rec.status = RECStatus.TRANSFERRED
                rec.sale_price_usd_mwh = price_usd_mwh
                sold += 1
                proceeds += price_usd_mwh

        return sold, proceeds

    def inventory(
        self,
        status: Optional[RECStatus] = None,
        energy_source: Optional[EnergySource] = None,
        vintage: Optional[str] = None,
    ) -> List[REC]:
        """Query REC inventory with optional filters."""
        recs = list(self._recs.values())
        if status:
            recs = [r for r in recs if r.status == status]
        if energy_source:
            recs = [r for r in recs if r.energy_source == energy_source]
        if vintage:
            recs = [r for r in recs if r.vintage_month == vintage]
        return recs

    def available_recs_mwh(self) -> Dict[str, float]:
        """Total available MWh by energy source."""
        result: Dict[str, float] = {}
        for rec in self.inventory(status=RECStatus.ACTIVE):
            src = rec.energy_source.value
            result[src] = result.get(src, 0.0) + rec.energy_mwh
        return result

    def compliance_check(
        self,
        obligation_mwh: float,
        qualifying_sources: Optional[List[EnergySource]] = None,
    ) -> Tuple[bool, float, float]:
        """
        Check if available RECs satisfy an RPS compliance obligation.

        Returns:
            (is_compliant, available_mwh, shortfall_mwh)
        """
        active = self.inventory(status=RECStatus.ACTIVE)
        if qualifying_sources:
            active = [r for r in active if r.energy_source in qualifying_sources]
        available = sum(r.energy_mwh for r in active)
        shortfall = max(0.0, obligation_mwh - available)
        return available >= obligation_mwh, available, shortfall
