"""m39_extraction — Claude-backed PDF portfolio & contract extraction.

Extracts structured asset and commercial-obligation data from operator-uploaded
PDFs using Anthropic's document vision + tool calling, scoring each field with a
confidence value and flagging low-confidence / ambiguous fields for human review.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import (
    DeliveryWindow,
    ExtractedAsset,
    ExtractedObligation,
    ExtractionResult,
    ExtractionReview,
)

if TYPE_CHECKING:
    from .extractor import PortfolioExtractor


def __getattr__(name: str) -> object:
    if name == "PortfolioExtractor":
        from .extractor import PortfolioExtractor as _PE  # noqa: PLC0415
        return _PE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "PortfolioExtractor",
    "ExtractedAsset",
    "ExtractedObligation",
    "DeliveryWindow",
    "ExtractionResult",
    "ExtractionReview",
]
