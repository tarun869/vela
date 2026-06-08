"""Pydantic models for the PDF portfolio & contract extraction pipeline.

These mirror the Anthropic tool input schemas in :mod:`vela.m39_extraction.tools`.
Every extracted record carries a ``confidence`` score (0-1); fields below
``CONFIDENCE_THRESHOLD`` are surfaced for human review before persistence.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Any field whose confidence is strictly below this is flagged for human review.
CONFIDENCE_THRESHOLD = 0.85

AssetType = Literal["BESS", "Solar", "Wind", "EV_Fleet", "Flex_Load"]
Chemistry = Literal["LFP", "NMC", "NCA"]
ObligationType = Literal[
    "capacity",
    "dr_event",
    "offtake",
    "reliability_reserve",
    "demand_charge",
]


class ExtractedAsset(BaseModel):
    """A single physical asset extracted from a portfolio/interconnection document."""

    asset_id: str
    asset_type: AssetType
    rated_mw: float
    rated_mwh: float | None = None
    iso_node: str | None = None
    qse_name: str | None = None
    chemistry: Chemistry | None = None
    warranty_cycles: int | None = None
    warranty_years: int | None = None
    capacity_guarantee_pct: float | None = Field(
        default=None, description="e.g. 80.0 for an 80% end-of-warranty capacity guarantee"
    )
    commissioned_date: str | None = Field(
        default=None, description="ISO-8601 date string (YYYY-MM-DD)"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence in this extraction")
    source_text: str | None = Field(
        default=None, description="The exact sentence the values were drawn from"
    )


class DeliveryWindow(BaseModel):
    """A recurring delivery obligation window."""

    days: list[str] = Field(
        default_factory=list,
        description='e.g. ["Monday", "Tuesday"], ["Weekdays"], or ["All"]',
    )
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=0, le=23)


class ExtractedObligation(BaseModel):
    """A single commercial obligation extracted from a contract document."""

    obligation_type: ObligationType
    committed_mw: float
    delivery_windows: list[DeliveryWindow] = Field(default_factory=list)
    penalty_linear_per_mwh: float | None = None
    penalty_escalation_threshold_mwh: float | None = None
    penalty_escalation_multiplier: float | None = None
    contract_start: str | None = Field(default=None, description="ISO-8601 date string")
    contract_end: str | None = Field(default=None, description="ISO-8601 date string")
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence in this extraction")
    ambiguous_language: str | None = Field(
        default=None,
        description="The exact penalty/obligation clause that has multiple interpretations",
    )
    source_text: str | None = Field(
        default=None, description="The exact sentence the values were drawn from"
    )


class ExtractionResult(BaseModel):
    """Aggregate result of one extraction call across one or more documents."""

    assets: list[ExtractedAsset] = Field(default_factory=list)
    obligations: list[ExtractedObligation] = Field(default_factory=list)
    low_confidence_fields: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Auto-populated: any record with confidence < CONFIDENCE_THRESHOLD",
    )
    extraction_warnings: list[str] = Field(default_factory=list)
    raw_claude_reasoning: str | None = None


class ExtractionReview(BaseModel):
    """Human-confirmation view layered over an :class:`ExtractionResult`."""

    result: ExtractionResult
    requires_human_review: bool = False
    review_items: list[dict[str, Any]] = Field(default_factory=list)
