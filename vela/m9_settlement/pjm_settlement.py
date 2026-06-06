"""PJM-specific settlement logic for energy, capacity, and ancillary services."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class PJMEnergySettlementInterval(NamedTuple):
    interval_start: datetime
    da_schedule_mwh: float
    rt_dispatch_mwh: float
    da_lmp: float
    rt_lmp: float
    congestion_component: float
    loss_component: float
    da_energy_revenue: float
    rt_balancing_revenue: float   # (RT-DA) at RT LMP
    total_revenue: float


class PJMCapacitySettlement(NamedTuple):
    asset_id: str
    delivery_year: str
    committed_ucap_mw: float
    actual_ucap_mw: float
    clearing_price_per_mw_day: float
    annual_revenue: float
    performance_charge: float    # Penalty if performance obligation missed
    net_revenue: float


@dataclass
class PJMSettlementEngine:
    """
    PJM energy and capacity market settlement.

    PJM has a locational marginal pricing (LMP) system with three components:
    1. Energy component (system-wide)
    2. Congestion component (location-specific)
    3. Loss component (distribution losses)

    Settlement: DA schedule at DA LMP + RT deviation at RT LMP
    """
    asset_id: str
    zone: str = "MAAC"          # PJM pricing zone or node

    def calculate_energy_settlement(
        self,
        da_schedule: list[float],    # MW (positive=injection)
        rt_dispatch: list[float],
        da_lmp: list[float],
        rt_lmp: list[float],
        congestion: list[float] | None = None,  # Congestion component $/MWh
        losses: list[float] | None = None,       # Loss component $/MWh
        start_time: datetime = None,
        dt_hours: float = 1.0,
    ) -> list[PJMEnergySettlementInterval]:
        """Calculate PJM two-settlement energy revenue."""
        if start_time is None:
            start_time = datetime.utcnow().replace(minute=0, second=0, microsecond=0)

        T = min(len(da_schedule), len(rt_dispatch), len(da_lmp), len(rt_lmp))
        cong = congestion or [0.0] * T
        loss = losses or [0.0] * T

        intervals = []
        for t in range(T):
            ts = start_time + timedelta(hours=t * dt_hours)
            da_mwh = da_schedule[t] * dt_hours
            rt_mwh = rt_dispatch[t] * dt_hours

            # DA settlement
            da_rev = da_mwh * da_lmp[t]
            # RT balancing: deviation quantity at RT LMP
            rt_bal = (rt_mwh - da_mwh) * rt_lmp[t]
            total = da_rev + rt_bal

            intervals.append(PJMEnergySettlementInterval(
                interval_start=ts,
                da_schedule_mwh=da_mwh,
                rt_dispatch_mwh=rt_mwh,
                da_lmp=da_lmp[t],
                rt_lmp=rt_lmp[t],
                congestion_component=cong[t],
                loss_component=loss[t],
                da_energy_revenue=da_rev,
                rt_balancing_revenue=rt_bal,
                total_revenue=total,
            ))

        logger.info(
            "PJM energy settlement %s: total=$%.2f over %d intervals",
            self.asset_id, sum(i.total_revenue for i in intervals), T
        )
        return intervals

    def calculate_capacity_settlement(
        self,
        delivery_year: str,
        committed_ucap_mw: float,
        clearing_price_per_mw_day: float,
        performance_assessment_hours: list[bool],  # True = asset was obligated
        actual_output: list[float],                # MW during PAH
        obligation_mw: float,                      # MW required during PAH
        dt_hours: float = 1.0,
    ) -> PJMCapacitySettlement:
        """
        PJM RPM capacity market settlement.

        Capacity resources receive:
            base_revenue = UCAP_MW * clearing_price * days

        Performance charge for non-performance during Performance Assessment Hours:
            penalty = max(0, obligation - actual) * penalty_rate * hours
        """
        days_in_year = 365
        annual_base = committed_ucap_mw * clearing_price_per_mw_day * days_in_year

        # Performance assessment
        penalty = 0.0
        pah_penalty_rate = clearing_price_per_mw_day * 3.0  # PJM-style 3x penalty multiplier ($/MW-day)

        for t, is_pah in enumerate(performance_assessment_hours):
            if is_pah and t < len(actual_output):
                shortfall = max(0.0, obligation_mw - actual_output[t])
                penalty += shortfall * pah_penalty_rate / 24 * dt_hours

        actual_ucap = committed_ucap_mw  # simplified; in reality measured
        net = annual_base - penalty

        return PJMCapacitySettlement(
            asset_id=self.asset_id,
            delivery_year=delivery_year,
            committed_ucap_mw=committed_ucap_mw,
            actual_ucap_mw=actual_ucap,
            clearing_price_per_mw_day=clearing_price_per_mw_day,
            annual_revenue=annual_base,
            performance_charge=penalty,
            net_revenue=net,
        )

    def calculate_ancillary_settlement(
        self,
        product: str,
        awarded_mw: list[float],
        clearing_price: list[float],
        performance_scores: list[float],
        dt_hours: float = 1.0,
    ) -> dict[str, float]:
        """
        PJM ancillary service settlement (Regulation, Synchronized Reserve).

        PJM pays:
        - Capacity payment: awarded_mw * clearing_price * dt
        - Performance payment: capacity_payment * performance_score bonus
        """
        T = min(len(awarded_mw), len(clearing_price), len(performance_scores))
        cap_payments = np.array(awarded_mw[:T]) * np.array(clearing_price[:T]) * dt_hours
        perf_bonus = cap_payments * np.array(performance_scores[:T])
        total = float(np.sum(cap_payments + perf_bonus))

        return {
            "product": product,
            "total_capacity_payment": float(np.sum(cap_payments)),
            "total_performance_payment": float(np.sum(perf_bonus)),
            "total_payment": total,
            "avg_clearing_price": float(np.mean(clearing_price[:T])),
            "avg_performance_score": float(np.mean(performance_scores[:T])),
        }

    def lmp_decomposition(
        self,
        total_lmp: list[float],
        congestion: list[float],
        losses: list[float],
    ) -> dict[str, list[float]]:
        """
        Decompose LMP into energy, congestion, and loss components.

        LMP = Energy + Congestion + Losses
        """
        total = np.array(total_lmp)
        cong = np.array(congestion)
        loss_arr = np.array(losses)
        energy = total - cong - loss_arr

        return {
            "energy": energy.tolist(),
            "congestion": cong.tolist(),
            "losses": loss_arr.tolist(),
            "total": total.tolist(),
            "avg_energy": float(np.mean(energy)),
            "avg_congestion": float(np.mean(cong)),
            "congestion_as_pct": float(np.mean(np.abs(cong) / (np.abs(total) + 1e-6)) * 100),
        }
