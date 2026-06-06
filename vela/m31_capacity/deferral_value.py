"""
Transmission and distribution investment deferral value computation.

VPP assets can defer costly grid upgrades by reducing peak demand.
This module quantifies that non-energy value stream.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class DeferralProject:
    project_id: str
    equipment_type: str         # "transformer", "line", "substation"
    current_loading_pct: float  # Current peak loading as % of capacity
    threshold_pct: float        # Upgrade triggered when loading exceeds this
    project_cost_usd: float     # Cost of grid upgrade
    planned_year: int           # Year upgrade was previously planned
    deferral_rate: float        # Annual load growth rate (fraction)


@dataclass
class DeferralResult:
    project_id: str
    vpp_capacity_needed_mw: float
    years_deferred: float
    npv_deferral_benefit_usd: float
    annualized_value_usd_mw_year: float


class TransmissionDeferralEngine:
    """
    Computes T&D investment deferral value for VPP assets.

    Methodology:
    1. Determine how much VPP capacity reduces peak load below threshold.
    2. Calculate how many years the grid upgrade is deferred.
    3. Compute NPV of the deferred capital cost.
    """

    def __init__(self, discount_rate: float = 0.07) -> None:
        self.discount_rate = discount_rate

    def years_deferred(
        self,
        project: DeferralProject,
        peak_reduction_pct: float,   # Percentage points of loading reduction
    ) -> float:
        """
        Compute years an upgrade can be deferred given peak reduction.

        Loading grows at deferral_rate per year.
        Time to reach threshold from (current - reduction) loading.
        """
        effective_loading = project.current_loading_pct - peak_reduction_pct
        if effective_loading < project.threshold_pct:
            excess_capacity = project.threshold_pct - effective_loading
            years = excess_capacity / (project.current_loading_pct * project.deferral_rate)
            return max(0.0, years)
        return 0.0

    def compute_deferral_value(
        self,
        project: DeferralProject,
        peak_reduction_mw: float,
        transformer_rating_mw: float,
    ) -> DeferralResult:
        """Compute NPV value of deferring a specific T&D upgrade."""
        peak_reduction_pct = peak_reduction_mw / max(transformer_rating_mw, 1.0) * 100.0
        deferred_years = self.years_deferred(project, peak_reduction_pct)

        # NPV = project_cost * (1 - 1/(1+r)^years_deferred)
        discount_factor = 1.0 / (1 + self.discount_rate) ** deferred_years
        npv_benefit = project.project_cost_usd * (1.0 - discount_factor)

        annualized = npv_benefit / max(peak_reduction_mw, 1.0) / max(deferred_years, 1.0)

        return DeferralResult(
            project_id=project.project_id,
            vpp_capacity_needed_mw=peak_reduction_mw,
            years_deferred=deferred_years,
            npv_deferral_benefit_usd=npv_benefit,
            annualized_value_usd_mw_year=annualized,
        )

    def portfolio_deferral_value(
        self,
        projects: List[DeferralProject],
        peak_reduction_mw: float,
        transformer_rating_mw: float,
    ) -> float:
        """Total deferral NPV across multiple projects."""
        return sum(
            self.compute_deferral_value(p, peak_reduction_mw, transformer_rating_mw).npv_deferral_benefit_usd
            for p in projects
        )
