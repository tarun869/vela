"""
Customer engagement engine for VPP program management.

Manages customer communications, gamification, and behavioral nudges
to improve DR event participation and long-term program retention.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class EngagementAction:
    action_id: str
    action_type: str      # "email", "sms", "push", "reward", "challenge"
    customer_id: str
    content: str
    scheduled_time: float
    sent: bool = False
    opened: bool = False
    clicked: bool = False


@dataclass
class Reward:
    customer_id: str
    reward_type: str    # "bill_credit", "points", "badge"
    amount: float
    reason: str
    issued_at: float = field(default_factory=time.time)
    redeemed: bool = False


@dataclass
class EngagementScore:
    customer_id: str
    score: float           # 0–100 composite engagement
    portal_activity: float
    dr_participation: float
    communication_response: float
    referral_count: int


class EngagementEngine:
    """
    Drives customer engagement through personalized nudges and rewards.

    Features:
    - Behavioral nudge scheduling based on energy events
    - Points/badge gamification system
    - Communication open/click tracking
    """

    def __init__(self) -> None:
        self._actions: List[EngagementAction] = []
        self._rewards: List[Reward] = []
        self._scores: Dict[str, EngagementScore] = {}

    def schedule_action(self, action: EngagementAction) -> None:
        self._actions.append(action)

    def issue_reward(self, reward: Reward) -> None:
        self._rewards.append(reward)

    def schedule_dr_nudge(
        self, customer_id: str, event_time: float, capacity_kw: float
    ) -> EngagementAction:
        """Schedule pre-event reminder for DR participation."""
        import uuid
        content = (
            f"Energy event starting soon! Your {capacity_kw:.0f} kW reduction "
            f"will earn bill credits. Tap to confirm."
        )
        action = EngagementAction(
            action_id=str(uuid.uuid4())[:8],
            action_type="push",
            customer_id=customer_id,
            content=content,
            scheduled_time=event_time - 3600,  # 1 hour before
        )
        self._actions.append(action)
        return action

    def compute_engagement_score(
        self,
        customer_id: str,
        login_count_30d: int,
        dr_events_participated: int,
        dr_events_called: int,
        email_open_rate: float,
        referrals: int,
    ) -> EngagementScore:
        """Compute composite engagement score."""
        portal = min(100.0, login_count_30d * 10)
        dr_rate = (dr_events_participated / max(dr_events_called, 1)) * 100
        comm = email_open_rate * 100

        score = 0.35 * portal + 0.40 * dr_rate + 0.15 * comm + 0.10 * min(100, referrals * 25)

        es = EngagementScore(
            customer_id=customer_id,
            score=round(score, 1),
            portal_activity=portal,
            dr_participation=dr_rate,
            communication_response=comm,
            referral_count=referrals,
        )
        self._scores[customer_id] = es
        return es

    def top_engaged_customers(self, top_n: int = 10) -> List[str]:
        return sorted(self._scores.keys(), key=lambda cid: -self._scores[cid].score)[:top_n]

    def pending_actions(self) -> List[EngagementAction]:
        now = time.time()
        return [a for a in self._actions if not a.sent and a.scheduled_time <= now]
