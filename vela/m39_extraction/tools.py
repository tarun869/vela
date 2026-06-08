"""Anthropic tool definitions for document extraction.

Plain dicts matching the Anthropic Messages API ``tools`` schema (NOT classes),
so they can be passed straight into ``client.messages.create(tools=...)``. The
input schemas mirror the Pydantic models in :mod:`vela.m39_extraction.models`.
"""
from __future__ import annotations

from typing import Any

_ASSET_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "asset_id": {
            "type": "string",
            "description": "The operator's identifier for the asset as written in the document.",
        },
        "asset_type": {
            "type": "string",
            "enum": ["BESS", "Solar", "Wind", "EV_Fleet", "Flex_Load"],
        },
        "rated_mw": {"type": "number", "description": "Nameplate power rating in MW."},
        "rated_mwh": {
            "type": ["number", "null"],
            "description": "Energy capacity in MWh (storage only); null otherwise.",
        },
        "iso_node": {
            "type": ["string", "null"],
            "description": "ISO/RTO pricing node or settlement point.",
        },
        "qse_name": {
            "type": ["string", "null"],
            "description": "Qualified Scheduling Entity / scheduling coordinator name.",
        },
        "chemistry": {
            "type": ["string", "null"],
            "enum": ["LFP", "NMC", "NCA", None],
            "description": "Battery cell chemistry (storage only).",
        },
        "warranty_cycles": {
            "type": ["integer", "null"],
            "description": "Warrantied number of full equivalent cycles.",
        },
        "warranty_years": {
            "type": ["integer", "null"],
            "description": "Warranty term in years.",
        },
        "capacity_guarantee_pct": {
            "type": ["number", "null"],
            "description": "End-of-warranty capacity guarantee percent, e.g. 80.0 for 80%.",
        },
        "commissioned_date": {
            "type": ["string", "null"],
            "description": "Commercial operation / commissioning date as ISO-8601 (YYYY-MM-DD).",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "Your confidence (0-1) in this asset's fields. Use < 0.85 for ANY value "
                "you inferred rather than read explicitly."
            ),
        },
        "source_text": {
            "type": ["string", "null"],
            "description": "The exact sentence in the document the values came from.",
        },
    },
    "required": ["asset_id", "asset_type", "rated_mw", "confidence"],
}

_DELIVERY_WINDOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "days": {
            "type": "array",
            "items": {"type": "string"},
            "description": 'e.g. ["Monday","Tuesday"], ["Weekdays"], or ["All"].',
        },
        "start_hour": {"type": "integer", "minimum": 0, "maximum": 23},
        "end_hour": {"type": "integer", "minimum": 0, "maximum": 23},
    },
    "required": ["days", "start_hour", "end_hour"],
}

_OBLIGATION_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "obligation_type": {
            "type": "string",
            "enum": [
                "capacity",
                "dr_event",
                "offtake",
                "reliability_reserve",
                "demand_charge",
            ],
        },
        "committed_mw": {"type": "number", "description": "Committed capacity/energy in MW."},
        "delivery_windows": {
            "type": "array",
            "items": _DELIVERY_WINDOW_SCHEMA,
        },
        "penalty_linear_per_mwh": {
            "type": ["number", "null"],
            "description": "Linear penalty in $/MWh of shortfall.",
        },
        "penalty_escalation_threshold_mwh": {
            "type": ["number", "null"],
            "description": "Shortfall MWh beyond which the escalated penalty multiplier applies.",
        },
        "penalty_escalation_multiplier": {
            "type": ["number", "null"],
            "description": "Multiplier applied to the linear penalty past the threshold.",
        },
        "contract_start": {"type": ["string", "null"], "description": "ISO-8601 date string."},
        "contract_end": {"type": ["string", "null"], "description": "ISO-8601 date string."},
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "Your confidence (0-1) in this obligation. Use < 0.85 for ANY value inferred "
                "rather than explicitly stated."
            ),
        },
        "ambiguous_language": {
            "type": ["string", "null"],
            "description": (
                "Quote the EXACT clause verbatim if the penalty or obligation language has "
                "more than one reasonable interpretation; otherwise null."
            ),
        },
        "source_text": {
            "type": ["string", "null"],
            "description": "The exact sentence in the document the values came from.",
        },
    },
    "required": ["obligation_type", "committed_mw", "confidence"],
}

EXTRACT_ASSET_PORTFOLIO_TOOL: dict[str, Any] = {
    "name": "extract_asset_portfolio",
    "description": (
        "Record every physical asset found in the asset portfolio / interconnection "
        "agreement document. Call once with all assets."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "assets": {
                "type": "array",
                "items": _ASSET_ITEM_SCHEMA,
            }
        },
        "required": ["assets"],
    },
}

EXTRACT_OBLIGATIONS_TOOL: dict[str, Any] = {
    "name": "extract_obligations",
    "description": (
        "Record every commercial obligation found in the contract / commercial "
        "obligations document. Call once with all obligations."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "obligations": {
                "type": "array",
                "items": _OBLIGATION_ITEM_SCHEMA,
            }
        },
        "required": ["obligations"],
    },
}

# Convenience: the full toolset passed to the Messages API.
EXTRACTION_TOOLS: list[dict[str, Any]] = [
    EXTRACT_ASSET_PORTFOLIO_TOOL,
    EXTRACT_OBLIGATIONS_TOOL,
]
