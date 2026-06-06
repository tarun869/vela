"""
Offtake agreement modeling for VPP energy products.

Covers tolling agreements, energy storage as a service (ESaaS),
and commercial offtake structures with capacity guarantees.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class TollingAgreement:
    agreement_id: str
    owner_id: str            # Party owning the capacity
    toller_id: str           # Party dispatching the capacity
    capacity_mw: float
    monthly_fee_usd: float   # Fixed monthly capacity charge
    variable_om_usd_mwh: float
    heat_rate_mmbtu_mwh: float    # For gas-fired resources
    fuel_supplied_by: str         # "toller" or "owner"
    start_date: str
    term_years: float


@dataclass
class ESaaS:
    """Energy Storage as a Service agreement."""
    service_id: str
    customer_id: str
    storage_capacity_mwh: float
    power_capacity_mw: float
    monthly_fee_usd: float
    round_trip_efficiency: float = 0.88
    guaranteed_cycles_year: int = 250
    degradation_backstop_pct: float = 0.80   # Provider replaces if below this


@dataclass
class OfftakeSettlement:
    period: str
    energy_delivered_mwh: float
    capacity_payment_usd: float
    variable_payment_usd: float
    total_payment_usd: float
    performance_pct: float


class OfftakeAgreementEngine:
    """Manages offtake agreement settlements and performance tracking."""

    def settle_tolling(
        self,
        agreement: TollingAgreement,
        dispatch_mwh: float,
        fuel_price_usd_mmbtu: float,
        period: str,
    ) -> OfftakeSettlement:
        """Calculate tolling agreement settlement for one month."""
        fuel_cost = (
            dispatch_mwh * agreement.heat_rate_mmbtu_mwh * fuel_price_usd_mmbtu
            if agreement.fuel_supplied_by == "toller" else 0.0
        )
        variable = dispatch_mwh * agreement.variable_om_usd_mwh
        expected_dispatch = agreement.capacity_mw * 720 * 0.5  # 50% capacity factor
        performance = dispatch_mwh / max(expected_dispatch, 1.0)

        return OfftakeSettlement(
            period=period,
            energy_delivered_mwh=dispatch_mwh,
            capacity_payment_usd=agreement.monthly_fee_usd,
            variable_payment_usd=variable + fuel_cost,
            total_payment_usd=agreement.monthly_fee_usd + variable + fuel_cost,
            performance_pct=min(performance, 1.0),
        )

    def settle_esaas(
        self,
        esaas: ESaaS,
        cycles_delivered: int,
        period: str,
    ) -> OfftakeSettlement:
        """Calculate ESaaS settlement with performance adjustment."""
        performance = min(1.0, cycles_delivered / max(esaas.guaranteed_cycles_year / 12, 1))
        return OfftakeSettlement(
            period=period,
            energy_delivered_mwh=cycles_delivered * esaas.storage_capacity_mwh,
            capacity_payment_usd=esaas.monthly_fee_usd,
            variable_payment_usd=0.0,
            total_payment_usd=esaas.monthly_fee_usd,
            performance_pct=performance,
        )
