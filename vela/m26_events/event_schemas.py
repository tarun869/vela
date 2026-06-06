"""
Canonical event schema definitions for all VPP domain events.

Provides typed event factory functions and validation for all
events flowing through the Vela event bus and event store.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

# Dispatch events
DISPATCH_SCHEDULED = "dispatch.scheduled"
DISPATCH_EXECUTED = "dispatch.executed"
DISPATCH_CANCELLED = "dispatch.cancelled"
DISPATCH_FAILED = "dispatch.failed"

# Battery events
BATTERY_SOC_CHANGED = "battery.soc_changed"
BATTERY_DEGRADATION_THRESHOLD = "battery.degradation_threshold"
BATTERY_FAULT_DETECTED = "battery.fault_detected"

# Market events
MARKET_PRICE_SPIKE = "market.price_spike"
MARKET_BID_ACCEPTED = "market.bid_accepted"
MARKET_BID_REJECTED = "market.bid_rejected"
MARKET_SETTLEMENT_COMPLETE = "market.settlement_complete"

# DR events
DR_EVENT_ISSUED = "dr.event_issued"
DR_DISPATCH_SENT = "dr.dispatch_sent"
DR_PERFORMANCE_MEASURED = "dr.performance_measured"

# Alert events
ALERT_FREQUENCY_DEVIATION = "alert.frequency_deviation"
ALERT_VOLTAGE_VIOLATION = "alert.voltage_violation"
ALERT_CYBER_ANOMALY = "alert.cyber_anomaly"
ALERT_LIMIT_BREACH = "alert.limit_breach"


# ---------------------------------------------------------------------------
# Typed event payload factories
# ---------------------------------------------------------------------------

def dispatch_scheduled_event(
    resource_id: str,
    power_mw: float,
    duration_h: float,
    interval: str,
    service: str,
) -> Dict[str, Any]:
    return {
        "resource_id": resource_id,
        "power_mw": power_mw,
        "duration_h": duration_h,
        "interval": interval,
        "service": service,
    }


def battery_soc_changed_event(
    asset_id: str,
    old_soc: float,
    new_soc: float,
    energy_mwh: float,
) -> Dict[str, Any]:
    return {
        "asset_id": asset_id,
        "old_soc": old_soc,
        "new_soc": new_soc,
        "energy_mwh": energy_mwh,
        "delta_soc": new_soc - old_soc,
    }


def market_price_spike_event(
    hub: str,
    price_usd_mwh: float,
    threshold_usd_mwh: float,
    interval: str,
) -> Dict[str, Any]:
    return {
        "hub": hub,
        "price_usd_mwh": price_usd_mwh,
        "threshold_usd_mwh": threshold_usd_mwh,
        "interval": interval,
        "spike_factor": price_usd_mwh / max(threshold_usd_mwh, 1.0),
    }


def alert_limit_breach_event(
    limit_id: str,
    current_value: float,
    limit_value: float,
    owner: str,
) -> Dict[str, Any]:
    return {
        "limit_id": limit_id,
        "current_value": current_value,
        "limit_value": limit_value,
        "owner": owner,
        "overage_pct": (current_value - limit_value) / max(limit_value, 1.0) * 100,
    }


def validate_event_payload(event_type: str, payload: Dict[str, Any]) -> bool:
    """Basic structural validation for known event types."""
    required_fields = {
        DISPATCH_SCHEDULED: {"resource_id", "power_mw", "interval"},
        BATTERY_SOC_CHANGED: {"asset_id", "old_soc", "new_soc"},
        MARKET_PRICE_SPIKE: {"hub", "price_usd_mwh"},
        ALERT_LIMIT_BREACH: {"limit_id", "current_value", "limit_value"},
    }
    fields = required_fields.get(event_type, set())
    return all(f in payload for f in fields)
