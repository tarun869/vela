"""
Customer behavioral response model for demand response programs.

Models non-price factors affecting DR participation:
  - Habituation / event fatigue
  - Technology adoption (smart thermostat, EV, etc.)
  - Social norms and peer effects
  - Notification channel effectiveness
  - Opt-out behavior under event saturation
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class CustomerProfile:
    customer_id: str
    customer_class: str              # "residential", "commercial", "industrial"
    tech_adoption_score: float       # 0–1, higher = more tech-enabled
    price_sensitivity: float         # 0–1 (complements elasticity)
    event_fatigue_rate: float = 0.05  # Participation drop per event (0–1)
    social_influence: float = 0.1    # Susceptibility to peer effects (0–1)
    baseline_participation: float = 0.8  # Initial participation probability
    current_participation: float = 0.8   # Updated over time
    events_received: int = 0
    events_opted_out: int = 0
    notification_channel: str = "email"  # "app", "sms", "email", "in_home_display"


# Notification channel effectiveness multipliers
CHANNEL_EFFECTIVENESS: Dict[str, float] = {
    "in_home_display": 1.20,
    "app": 1.10,
    "sms": 1.05,
    "email": 0.90,
    "phone": 0.85,
}


class BehavioralResponseModel:
    """
    Models customer participation probability and load response
    including fatigue, learning, and social dynamics.
    """

    def __init__(self) -> None:
        self._customers: Dict[str, CustomerProfile] = {}

    def add_customer(self, profile: CustomerProfile) -> None:
        self._customers[profile.customer_id] = profile

    def _fatigue_factor(self, profile: CustomerProfile) -> float:
        """
        Participation probability decreases with event saturation.
        Uses exponential decay with recovery between events.
        """
        if profile.events_received == 0:
            return 1.0
        opt_out_rate = profile.events_opted_out / profile.events_received
        fatigue = math.exp(-profile.event_fatigue_rate * profile.events_received * opt_out_rate)
        return max(0.3, fatigue)

    def _tech_multiplier(self, profile: CustomerProfile) -> float:
        """More tech-enabled customers respond more reliably."""
        return 0.7 + 0.5 * profile.tech_adoption_score

    def _social_multiplier(self, community_participation: float, profile: CustomerProfile) -> float:
        """Peer effect: higher community participation boosts individual response."""
        social_boost = profile.social_influence * (community_participation - 0.5)
        return 1.0 + social_boost

    def participation_probability(
        self,
        customer_id: str,
        community_participation: float = 0.6,
        notice_hours: float = 2.0,
    ) -> float:
        """
        Compute current participation probability for a DR event.

        Args:
            customer_id: ID of the customer.
            community_participation: Fraction of neighbors participating (for social effect).
            notice_hours: Event notice time (hours).

        Returns:
            Probability of participation (0–1).
        """
        profile = self._customers[customer_id]
        channel_eff = CHANNEL_EFFECTIVENESS.get(profile.notification_channel, 0.9)

        # Notice time effect: too short notice reduces participation
        notice_factor = 1.0 - math.exp(-notice_hours / 4.0)  # Saturates at ~1.0 for >12h

        p = (
            profile.baseline_participation
            * self._fatigue_factor(profile)
            * self._tech_multiplier(profile)
            * self._social_multiplier(community_participation, profile)
            * channel_eff
            * notice_factor
        )
        return max(0.0, min(1.0, p))

    def expected_reduction_kw(
        self,
        customer_id: str,
        base_load_kw: float,
        max_curtailment_kw: float,
        **kwargs,
    ) -> float:
        """
        Expected load reduction accounting for participation probability.

        Returns:
            Expected kW reduction = participation_prob * max_curtailment.
        """
        p_participate = self.participation_probability(customer_id, **kwargs)
        return p_participate * max_curtailment_kw

    def update_after_event(
        self,
        customer_id: str,
        participated: bool,
        reduction_pct: float = 0.0,
    ) -> None:
        """
        Update customer profile after a DR event outcome.

        Positive performance increases future participation; opt-out increases fatigue.
        """
        profile = self._customers[customer_id]
        profile.events_received += 1

        if participated:
            # Positive reinforcement — slight increase in baseline participation
            delta = 0.02 * reduction_pct / 100.0
            profile.baseline_participation = min(0.95, profile.baseline_participation + delta)
        else:
            profile.events_opted_out += 1
            # Negative experience reduces future participation
            profile.baseline_participation = max(0.1, profile.baseline_participation - 0.05)

        profile.current_participation = self.participation_probability(customer_id)

    def fleet_expected_reduction(
        self,
        customer_loads: Dict[str, Tuple[float, float]],  # customer_id -> (base_kw, max_curtail_kw)
        community_participation: float = 0.6,
        notice_hours: float = 2.0,
    ) -> Dict[str, float]:
        """
        Compute expected reduction for the entire fleet.

        Returns dict of customer_id -> expected_reduction_kw.
        """
        return {
            cid: self.expected_reduction_kw(
                cid,
                base_load_kw=loads[0],
                max_curtailment_kw=loads[1],
                community_participation=community_participation,
                notice_hours=notice_hours,
            )
            for cid, loads in customer_loads.items()
            if cid in self._customers
        }

    def adoption_curve(
        self,
        n_periods: int,
        initial_tech_score: float = 0.3,
        adoption_rate: float = 0.05,
    ) -> List[float]:
        """
        Bass diffusion model for technology adoption over time.

        Returns list of tech adoption scores per period.
        """
        p_innov = 0.03    # Coefficient of innovation
        q_imitat = 0.38   # Coefficient of imitation
        m = 1.0           # Market saturation

        scores: List[float] = [initial_tech_score]
        for _ in range(n_periods - 1):
            f_t = scores[-1]
            n_new = (p_innov + q_imitat * f_t) * (m - f_t)
            scores.append(min(1.0, f_t + n_new * adoption_rate))
        return scores

    def churn_risk(self, customer_id: str) -> float:
        """
        Estimate DR program churn risk for a customer.
        High fatigue + low performance -> high churn risk.

        Returns:
            Churn risk score (0–1).
        """
        profile = self._customers[customer_id]
        if profile.events_received == 0:
            return 0.1
        opt_out_rate = profile.events_opted_out / profile.events_received
        fatigue = 1.0 - self._fatigue_factor(profile)
        return min(1.0, 0.6 * opt_out_rate + 0.4 * fatigue)
