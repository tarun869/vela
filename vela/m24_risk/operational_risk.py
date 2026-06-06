"""
Operational risk assessment for VPP systems.

Models equipment failure risk, software/system reliability, process
risks, and estimates capital at risk using loss distribution approach.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
import numpy as np


class RiskCategory(str, Enum):
    EQUIPMENT_FAILURE = "equipment_failure"
    CYBER_INCIDENT = "cyber_incident"
    COMMUNICATION_OUTAGE = "communication_outage"
    REGULATORY_NONCOMPLIANCE = "regulatory_noncompliance"
    PROCESS_ERROR = "process_error"
    NATURAL_DISASTER = "natural_disaster"


@dataclass
class OpRiskEvent:
    event_id: str
    category: RiskCategory
    description: str
    probability_annual: float    # Annual frequency (Poisson lambda)
    severity_mean_usd: float     # Log-normal distribution mean
    severity_std_usd: float      # Log-normal distribution std
    mitigant: Optional[str] = None
    residual_factor: float = 1.0   # 1.0 = no mitigation, 0.1 = 90% reduced


@dataclass
class OpRiskAssessment:
    total_expected_loss_usd_year: float
    var_99_usd_year: float
    expected_shortfall_usd_year: float
    top_risk_events: List[str]
    risk_by_category: Dict[str, float]


class OperationalRiskEngine:
    """
    Quantifies operational risks using Loss Distribution Approach (LDA).

    Models annual loss distribution using Monte Carlo simulation with
    Poisson frequency and log-normal severity per risk event.
    """

    def __init__(self, n_simulations: int = 10_000) -> None:
        self.n_sims = n_simulations
        self._events: Dict[str, OpRiskEvent] = {}

    def register_event(self, event: OpRiskEvent) -> None:
        self._events[event.event_id] = event

    def simulate_annual_losses(self, seed: int = 42) -> np.ndarray:
        """
        Monte Carlo simulation of total annual operational losses.

        For each simulation:
        - Draw frequency from Poisson(lambda * residual_factor)
        - Draw severity for each occurrence from LogNormal(mu, sigma)
        - Sum losses
        """
        rng = np.random.default_rng(seed)
        total_losses = np.zeros(self.n_sims)

        for event in self._events.values():
            lam = event.probability_annual * event.residual_factor
            # Poisson frequency
            n_occurrences = rng.poisson(lam, size=self.n_sims)
            # Log-normal severity parameters
            mu = np.log(event.severity_mean_usd ** 2 / np.sqrt(
                event.severity_std_usd ** 2 + event.severity_mean_usd ** 2))
            sigma = np.sqrt(np.log(1 + event.severity_std_usd ** 2 / event.severity_mean_usd ** 2))

            for i in range(self.n_sims):
                if n_occurrences[i] > 0:
                    severities = rng.lognormal(mu, sigma, n_occurrences[i])
                    total_losses[i] += np.sum(severities)

        return total_losses

    def assess(self) -> OpRiskAssessment:
        """Run full operational risk assessment."""
        losses = self.simulate_annual_losses()
        var_99 = float(np.percentile(losses, 99))
        tail = losses[losses >= np.percentile(losses, 99)]
        es = float(np.mean(tail)) if len(tail) > 0 else var_99
        expected = float(np.mean(losses))

        # Risk by category
        risk_by_cat: Dict[str, float] = {}
        for ev in self._events.values():
            cat = ev.category.value
            el = ev.probability_annual * ev.severity_mean_usd * ev.residual_factor
            risk_by_cat[cat] = risk_by_cat.get(cat, 0.0) + el

        top_events = sorted(
            self._events.keys(),
            key=lambda eid: self._events[eid].probability_annual * self._events[eid].severity_mean_usd,
            reverse=True,
        )[:5]

        return OpRiskAssessment(
            total_expected_loss_usd_year=expected,
            var_99_usd_year=var_99,
            expected_shortfall_usd_year=es,
            top_risk_events=top_events,
            risk_by_category=risk_by_cat,
        )
