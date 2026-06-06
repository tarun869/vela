"""Human-readable dispatch decision narratives."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class DispatchNarrative:
    timestamp: datetime
    asset_id: str
    action: str
    power_mw: float
    price: float
    reason: str
    expected_revenue: float


def generate_narrative(
    asset_id: str,
    charge_mw: list[float],
    discharge_mw: list[float],
    lmp: list[float],
    timestamps: list[datetime],
) -> list[DispatchNarrative]:
    narratives = []
    for t, (c, d, p, ts) in enumerate(zip(charge_mw, discharge_mw, lmp, timestamps)):
        if d > 0.1:
            reason = f"Discharging at ${p:.2f}/MWh — above median price"
            revenue = d * p
            narratives.append(DispatchNarrative(ts, asset_id, "discharge", d, p, reason, revenue))
        elif c > 0.1:
            reason = f"Charging at ${p:.2f}/MWh — below median price, building SOC"
            narratives.append(DispatchNarrative(ts, asset_id, "charge", c, p, reason, -c * p))
    return narratives
