"""Performance scoring for ancillary service obligations."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple


class ASPerformanceScore(NamedTuple):
    asset_id: str
    product: str
    period: str
    awarded_mw: float
    delivered_mw: float
    performance_ratio: float    # delivered / awarded (0-1+)
    score: float                # Market-specific score
    performance_payment: float  # $ performance incentive/penalty
    status: str                 # "pass", "fail", "partial"


@dataclass
class ERCOTPerformanceScorer:
    """
    ERCOT ancillary service performance scoring.

    ERCOT uses pay-for-performance with performance multipliers.
    Resources that fail to respond face deployment penalties.

    For ECRS and RRS: must deploy within 10 minutes at full awarded MW.
    For Regulation: scored on mileage ratio (actual/committed mileage).
    """

    def score_rrs(
        self,
        asset_id: str,
        period: str,
        awarded_mw: float,
        response_mw: list[float],   # MW delivered during 10-minute response window
        event_timestamps: list[datetime],
        clearing_price: float,
    ) -> ASPerformanceScore:
        """
        Score RRS (Responsive Reserve Service) performance.

        ERCOT requirement: deliver awarded MW within 10 minutes of deployment.
        """
        if not response_mw:
            return ASPerformanceScore(
                asset_id=asset_id, product="RRS", period=period,
                awarded_mw=awarded_mw, delivered_mw=0.0,
                performance_ratio=0.0, score=0.0, performance_payment=0.0,
                status="fail"
            )

        # Peak response within 10-minute window
        delivered = max(response_mw)
        ratio = delivered / (awarded_mw + 1e-6)
        ratio = min(1.0, ratio)

        if ratio >= 0.95:
            status = "pass"
            score = 1.0
        elif ratio >= 0.75:
            status = "partial"
            score = ratio
        else:
            status = "fail"
            score = 0.0

        # Performance payment: awarded MW * clearing price * 0.5h duration * score
        payment = awarded_mw * clearing_price * 0.5 * score

        return ASPerformanceScore(
            asset_id=asset_id, product="RRS", period=period,
            awarded_mw=awarded_mw, delivered_mw=delivered,
            performance_ratio=ratio, score=score,
            performance_payment=payment, status=status,
        )

    def score_regulation(
        self,
        asset_id: str,
        period: str,
        awarded_mw: float,
        agc_signal: list[float],     # Normalized AGC signal (-1 to 1)
        actual_response: list[float],  # Actual MW response
        clearing_price: float,
        mileage_ratio_target: float = 1.0,
    ) -> ASPerformanceScore:
        """
        Score regulation performance based on AGC tracking accuracy.

        Mileage = total MW traversed (integral of |d(response)/dt|).
        Performance = actual mileage / expected mileage.
        """
        commanded = np.array(agc_signal) * awarded_mw
        actual = np.array(actual_response[:len(commanded)])

        # Tracking accuracy: correlation between command and response
        tracking_error = np.abs(commanded - actual)
        mean_error = float(np.mean(tracking_error))
        tracking_accuracy = max(0.0, 1.0 - mean_error / (awarded_mw + 1e-6))

        # Mileage
        if len(actual) > 1:
            actual_mileage = float(np.sum(np.abs(np.diff(actual))))
            commanded_mileage = float(np.sum(np.abs(np.diff(commanded))))
            if commanded_mileage > 0:
                mileage_ratio = actual_mileage / commanded_mileage
            else:
                mileage_ratio = 1.0
        else:
            mileage_ratio = 1.0

        # Combined score: tracking + mileage
        score = float(np.clip(0.6 * tracking_accuracy + 0.4 * min(1.0, mileage_ratio), 0, 1.1))

        status = "pass" if score >= 0.95 else ("partial" if score >= 0.75 else "fail")
        payment = awarded_mw * clearing_price * score

        return ASPerformanceScore(
            asset_id=asset_id, product="REG", period=period,
            awarded_mw=awarded_mw, delivered_mw=float(np.mean(np.abs(actual))),
            performance_ratio=tracking_accuracy, score=score,
            performance_payment=payment, status=status,
        )


@dataclass
class CAISOPerformanceScorer:
    """
    CAISO regulation performance scoring.

    CAISO uses Performance Incentive Rate (PIR) system:
    - Performance score = mileage ratio * accuracy score
    - Payment = capacity_payment + score * performance_payment_rate * mileage
    """
    pir_rate: float = 0.10  # $/MWh performance incentive rate

    def score_regulation(
        self,
        asset_id: str,
        period: str,
        awarded_mw: float,
        agc_signal: list[float],
        actual_response: list[float],
        cap_price: float,       # $/MW-h capacity payment
        perf_price: float,      # $/MWh performance payment
        dt_hours: float = 1.0,
    ) -> ASPerformanceScore:
        """CAISO regulation performance score."""
        T = min(len(agc_signal), len(actual_response))
        commanded = np.array(agc_signal[:T]) * awarded_mw
        actual = np.array(actual_response[:T])

        # Tracking score
        error = np.abs(commanded - actual)
        avg_error = float(np.mean(error))
        score = max(0.0, 1.0 - avg_error / (awarded_mw + 1e-6))

        # Mileage
        if T > 1:
            mileage = float(np.sum(np.abs(np.diff(actual))))
        else:
            mileage = 0.0

        # Payment: capacity + performance
        cap_payment = awarded_mw * cap_price * T * dt_hours
        perf_payment = mileage * perf_price * score

        total_payment = cap_payment + perf_payment
        status = "pass" if score >= 0.90 else "partial"

        return ASPerformanceScore(
            asset_id=asset_id, product="REG_CAISO", period=period,
            awarded_mw=awarded_mw, delivered_mw=float(np.mean(np.abs(actual))),
            performance_ratio=score, score=score,
            performance_payment=total_payment, status=status,
        )


@dataclass
class PortfolioPerformanceTracker:
    """Tracks AS performance across a fleet of assets over time."""
    _history: list[ASPerformanceScore] = field(default_factory=list, init=False, repr=False)

    def record(self, score: ASPerformanceScore) -> None:
        self._history.append(score)

    def summary(self, asset_id: str | None = None) -> dict[str, float]:
        records = self._history
        if asset_id:
            records = [r for r in records if r.asset_id == asset_id]
        if not records:
            return {}
        scores = np.array([r.score for r in records])
        payments = np.array([r.performance_payment for r in records])
        pass_rate = np.mean([r.status == "pass" for r in records])
        return {
            "avg_score": float(np.mean(scores)),
            "min_score": float(np.min(scores)),
            "total_performance_payment": float(np.sum(payments)),
            "pass_rate": float(pass_rate),
            "n_events": float(len(records)),
        }
