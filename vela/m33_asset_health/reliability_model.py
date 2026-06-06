"""
Reliability modeling for VPP fleet capacity assurance.

Computes fleet-level availability, expected generation shortfall
risk, and reliability contribution for resource adequacy planning.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import numpy as np


@dataclass
class AssetReliability:
    asset_id: str
    forced_outage_rate: float     # FOR: fraction of time on forced outage
    scheduled_outage_rate: float  # SOR: planned maintenance fraction
    capacity_mw: float
    min_output_mw: float = 0.0


@dataclass
class FleetReliabilityResult:
    expected_available_mw: float
    efor_fleet: float             # Equivalent Forced Outage Rate for fleet
    lolp_percent: float           # Loss of Load Probability estimate
    expected_unserved_energy_mwh: float   # EUE
    effective_load_carrying_capability: float  # ELCC (MW)


class ReliabilityModel:
    """
    Computes fleet reliability metrics for VPP resource adequacy.

    Uses simplified analytical approach based on individual asset
    forced outage rates and independence assumption.
    """

    def __init__(self, n_simulations: int = 10_000) -> None:
        self.n_sims = n_simulations

    def fleet_availability(self, assets: List[AssetReliability]) -> float:
        """
        Expected available capacity = sum(capacity * availability).
        Availability = 1 - FOR - SOR.
        """
        return sum(
            a.capacity_mw * (1 - a.forced_outage_rate - a.scheduled_outage_rate)
            for a in assets
        )

    def monte_carlo_reliability(
        self,
        assets: List[AssetReliability],
        load_mw: float,
        seed: int = 42,
    ) -> FleetReliabilityResult:
        """
        Monte Carlo simulation of fleet reliability.

        For each simulation:
        - Sample each asset's outage state (Bernoulli with FOR)
        - Compute available capacity
        - Check if capacity >= load (LOLP)
        """
        rng = np.random.default_rng(seed)
        n = self.n_sims
        caps = np.array([a.capacity_mw for a in assets])
        fors = np.array([a.forced_outage_rate for a in assets])

        # Outage state: 1 = online, 0 = on forced outage
        outage_states = rng.random((n, len(assets))) >= fors
        available = (caps * outage_states).sum(axis=1)

        lolp = float(np.mean(available < load_mw))
        shortfall = np.maximum(0.0, load_mw - available)
        eue = float(np.mean(shortfall))
        efor_fleet = float(1.0 - np.mean(available) / max(np.sum(caps), 1.0))

        # ELCC: capacity of ideal generator that provides same LOLP reduction
        # Simplified: ELCC ≈ (1 - EFOR_fleet) * min(fleet_capacity, load)
        elcc = (1 - efor_fleet) * min(np.sum(caps), load_mw)

        return FleetReliabilityResult(
            expected_available_mw=float(np.mean(available)),
            efor_fleet=efor_fleet,
            lolp_percent=lolp * 100,
            expected_unserved_energy_mwh=eue,
            effective_load_carrying_capability=elcc,
        )
