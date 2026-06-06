"""
Customer churn prediction for VPP program retention management.

Predicts probability of customer unenrollment using behavioral
and financial features, enabling proactive retention campaigns.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np


@dataclass
class CustomerChurnFeatures:
    customer_id: str
    months_enrolled: int
    monthly_savings_avg_usd: float
    dr_event_compliance_rate: float   # 0–1
    support_tickets_last_90d: int
    last_login_days_ago: int          # Portal/app inactivity
    nps_score: Optional[int]          # -100 to 100
    peak_demand_reduction_pct: float
    payment_on_time_rate: float


@dataclass
class ChurnPrediction:
    customer_id: str
    churn_probability: float     # 0–1
    churn_risk_label: str        # "low", "medium", "high"
    top_risk_factors: List[str]
    recommended_intervention: str


class ChurnPredictor:
    """
    Logistic regression-inspired churn predictor using domain knowledge
    feature weights.

    In production, this would be trained with scikit-learn on labeled data.
    """

    # Feature weights (positive = increases churn risk)
    WEIGHTS = {
        "months_enrolled_discount": -0.05,    # Loyalty reduces churn
        "savings_shortfall": 0.15,            # Low savings increases churn
        "compliance_shortfall": 0.20,         # Poor event compliance
        "support_tickets": 0.10,              # Frustration signal
        "inactivity": 0.12,                   # Portal disengagement
        "nps_negative": 0.25,                 # Promoter vs detractor
        "payment_late": 0.18,                 # Financial strain
    }

    def predict(self, features: CustomerChurnFeatures) -> ChurnPrediction:
        """Compute churn probability and identify key risk factors."""
        score = 0.0
        risk_factors: List[str] = []

        # Loyalty discount
        loyalty = -self.WEIGHTS["months_enrolled_discount"] * min(features.months_enrolled, 24)
        score += loyalty

        # Savings shortfall (threshold: $50/month)
        if features.monthly_savings_avg_usd < 50:
            delta = self.WEIGHTS["savings_shortfall"] * (1.0 - features.monthly_savings_avg_usd / 50.0)
            score += delta
            risk_factors.append("low_savings")

        # DR compliance
        if features.dr_event_compliance_rate < 0.80:
            delta = self.WEIGHTS["compliance_shortfall"] * (0.80 - features.dr_event_compliance_rate)
            score += delta
            risk_factors.append("poor_dr_compliance")

        # Support tickets
        if features.support_tickets_last_90d > 2:
            delta = self.WEIGHTS["support_tickets"] * features.support_tickets_last_90d
            score += delta
            risk_factors.append("high_support_volume")

        # Portal inactivity
        if features.last_login_days_ago > 30:
            delta = self.WEIGHTS["inactivity"] * (features.last_login_days_ago / 90.0)
            score += delta
            risk_factors.append("portal_inactivity")

        # NPS
        if features.nps_score is not None and features.nps_score < 0:
            delta = self.WEIGHTS["nps_negative"]
            score += delta
            risk_factors.append("negative_nps")

        # Payment history
        if features.payment_on_time_rate < 0.90:
            delta = self.WEIGHTS["payment_late"] * (0.90 - features.payment_on_time_rate)
            score += delta
            risk_factors.append("payment_issues")

        prob = 1.0 / (1.0 + np.exp(-score))   # Sigmoid

        if prob >= 0.70:
            label = "high"
            action = "immediate_outreach_with_incentive"
        elif prob >= 0.40:
            label = "medium"
            action = "schedule_account_review"
        else:
            label = "low"
            action = "standard_engagement"

        return ChurnPrediction(
            customer_id=features.customer_id,
            churn_probability=float(prob),
            churn_risk_label=label,
            top_risk_factors=risk_factors[:3],
            recommended_intervention=action,
        )
