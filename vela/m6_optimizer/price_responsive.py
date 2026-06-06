"""Price-responsive dispatch without formal optimization — rule-based fast control."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple


class PRDispatchAction(NamedTuple):
    timestamp: datetime | None
    charge_mw: float
    discharge_mw: float
    soc_pct: float
    reason: str
    revenue: float


@dataclass
class PriceThresholdPolicy:
    """
    Price-responsive dispatch policy using static price thresholds.

    Simple but effective for real-time control when:
    - Solver latency is unacceptable
    - Market rules require sub-second response
    - Price thresholds are contractually defined (e.g., demand response programs)

    Policy logic:
    - Price > discharge_threshold: discharge at max power
    - Price < charge_threshold: charge at max power
    - Otherwise: idle or hold SOC
    """
    charge_threshold: float = 25.0     # $/MWh — charge below this price
    discharge_threshold: float = 60.0  # $/MWh — discharge above this price
    capacity_mwh: float = 10.0
    power_mw: float = 5.0
    rte: float = 0.92
    soc_min: float = 0.05
    soc_max: float = 0.95
    dt_hours: float = 1.0
    _soc: float = field(default=0.5, init=False, repr=False)

    def reset(self, soc: float = 0.5) -> None:
        self._soc = float(np.clip(soc, self.soc_min, self.soc_max))

    @property
    def soc(self) -> float:
        return self._soc

    def act(self, price: float, timestamp: datetime | None = None) -> PRDispatchAction:
        """Execute one dispatch interval."""
        if price >= self.discharge_threshold and self._soc > self.soc_min + 0.02:
            dis = min(self.power_mw, (self._soc - self.soc_min) * self.capacity_mwh / self.dt_hours)
            self._soc -= dis * self.dt_hours / self.capacity_mwh
            return PRDispatchAction(
                timestamp=timestamp,
                charge_mw=0.0,
                discharge_mw=dis,
                soc_pct=self._soc,
                reason=f"Price ${price:.1f}/MWh >= threshold ${self.discharge_threshold:.1f}",
                revenue=dis * price * self.dt_hours,
            )
        elif price <= self.charge_threshold and self._soc < self.soc_max - 0.02:
            ch = min(self.power_mw, (self.soc_max - self._soc) * self.capacity_mwh / self.dt_hours)
            self._soc += ch * self.rte * self.dt_hours / self.capacity_mwh
            return PRDispatchAction(
                timestamp=timestamp,
                charge_mw=ch,
                discharge_mw=0.0,
                soc_pct=self._soc,
                reason=f"Price ${price:.1f}/MWh <= threshold ${self.charge_threshold:.1f}",
                revenue=-ch * price * self.dt_hours,
            )
        else:
            return PRDispatchAction(
                timestamp=timestamp,
                charge_mw=0.0,
                discharge_mw=0.0,
                soc_pct=self._soc,
                reason=f"Price ${price:.1f}/MWh in neutral band",
                revenue=0.0,
            )


@dataclass
class AdaptiveThresholdPolicy:
    """
    Price-responsive policy with thresholds adapted to rolling price statistics.

    Charge threshold = rolling_mean - k_low * rolling_std
    Discharge threshold = rolling_mean + k_high * rolling_std

    Adapts to local price conditions rather than relying on fixed thresholds.
    """
    k_low: float = 0.8      # Charge when price < mean - k_low * std
    k_high: float = 0.8     # Discharge when price > mean + k_high * std
    window_hours: int = 24
    capacity_mwh: float = 10.0
    power_mw: float = 5.0
    rte: float = 0.92
    soc_min: float = 0.05
    soc_max: float = 0.95
    dt_hours: float = 1.0
    _soc: float = field(default=0.5, init=False, repr=False)
    _price_history: list[float] = field(default_factory=list, init=False, repr=False)

    def reset(self, soc: float = 0.5) -> None:
        self._soc = float(np.clip(soc, self.soc_min, self.soc_max))
        self._price_history.clear()

    @property
    def current_thresholds(self) -> tuple[float, float]:
        """Returns (charge_threshold, discharge_threshold)."""
        if len(self._price_history) < 4:
            return 25.0, 60.0  # default
        arr = np.array(self._price_history[-self.window_hours:])
        mu, sigma = float(np.mean(arr)), float(np.std(arr))
        return mu - self.k_low * sigma, mu + self.k_high * sigma

    def act(self, price: float, timestamp: datetime | None = None) -> PRDispatchAction:
        self._price_history.append(price)
        ch_thresh, dis_thresh = self.current_thresholds

        if price >= dis_thresh and self._soc > self.soc_min + 0.02:
            dis = min(self.power_mw, (self._soc - self.soc_min) * self.capacity_mwh / self.dt_hours)
            self._soc -= dis * self.dt_hours / self.capacity_mwh
            return PRDispatchAction(
                timestamp=timestamp, charge_mw=0.0, discharge_mw=dis,
                soc_pct=self._soc,
                reason=f"Price ${price:.1f} >= adaptive threshold ${dis_thresh:.1f}",
                revenue=dis * price * self.dt_hours,
            )
        elif price <= ch_thresh and self._soc < self.soc_max - 0.02:
            ch = min(self.power_mw, (self.soc_max - self._soc) * self.capacity_mwh / self.dt_hours)
            self._soc += ch * self.rte * self.dt_hours / self.capacity_mwh
            return PRDispatchAction(
                timestamp=timestamp, charge_mw=ch, discharge_mw=0.0,
                soc_pct=self._soc,
                reason=f"Price ${price:.1f} <= adaptive threshold ${ch_thresh:.1f}",
                revenue=-ch * price * self.dt_hours,
            )
        else:
            return PRDispatchAction(
                timestamp=timestamp, charge_mw=0.0, discharge_mw=0.0,
                soc_pct=self._soc, reason="Neutral band", revenue=0.0,
            )


@dataclass
class DemandResponseController:
    """
    Demand response dispatch controller.

    Curtails flexible load in response to:
    - Direct Load Control (DLC) signals from utility
    - Price-based triggers
    - Emergency events (NERC Level 1/2/3)
    """
    baseline_load_mw: float = 10.0
    curtailment_limit_mw: float = 3.0       # Max curtailment
    rebound_factor: float = 0.7             # Load rebound after DR event
    min_event_separation_h: int = 4         # Minimum hours between events
    _last_event_hour: int = field(default=-999, init=False, repr=False)

    def respond(
        self,
        current_hour: int,
        price: float,
        activation_threshold: float = 80.0,
    ) -> dict[str, float]:
        """
        Determine DR response.

        Returns dict with curtailment_mw and net_load_mw.
        """
        if current_hour - self._last_event_hour < self.min_event_separation_h:
            return {"curtailment_mw": 0.0, "net_load_mw": self.baseline_load_mw, "event": False}

        if price >= activation_threshold:
            curtail = min(self.curtailment_limit_mw, self.baseline_load_mw * 0.3)
            self._last_event_hour = current_hour
            return {
                "curtailment_mw": curtail,
                "net_load_mw": self.baseline_load_mw - curtail,
                "event": True,
                "reason": f"DR activated at ${price:.1f}/MWh >= ${activation_threshold:.1f}",
            }
        return {"curtailment_mw": 0.0, "net_load_mw": self.baseline_load_mw, "event": False}
