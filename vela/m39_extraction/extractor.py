"""Claude-backed extraction of structured asset & obligation data from PDFs.

Uses the raw Anthropic SDK (no LangChain) with document vision + tool calling.
The model is pinned to ``claude-sonnet-4-6``; ``tool_choice`` is ``auto`` so Claude
only calls the tool(s) relevant to the document(s) it is given.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Literal

import anthropic

from vela.security.secrets import get_anthropic_api_key

from .models import (
    CONFIDENCE_THRESHOLD,
    ExtractedAsset,
    ExtractedObligation,
    ExtractionResult,
    ExtractionReview,
)
from .tools import EXTRACTION_TOOLS

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192

DocType = Literal["portfolio", "contract", "combined"]

SYSTEM_PROMPT = """\
You are the document-extraction engine for Vela, a Virtual Power Plant (VPP) \
dispatch-optimization platform. You are part of an OPERATOR ONBOARDING workflow: a \
human operator has uploaded asset-portfolio / interconnection documents and/or \
commercial-obligation contracts, and your structured output is reviewed by that \
operator before anything is persisted or dispatched against.

Extract data ONLY using the provided tools. Follow these rules exactly:

1. CONFIDENCE: Every record carries a `confidence` from 0 to 1. Set confidence \
strictly BELOW 0.85 for ANY field you inferred, computed, or guessed rather than \
read explicitly in the document. Reserve confidence >= 0.85 for values stated \
verbatim and unambiguously.

2. SOURCE TEXT: For every record set `source_text` to the EXACT sentence (verbatim, \
not paraphrased) from which you drew the values.

3. AMBIGUOUS PENALTY LANGUAGE: For obligations, if any penalty or delivery clause \
admits more than one reasonable interpretation, quote the EXACT clause verbatim in \
`ambiguous_language`. Otherwise leave it null.

4. MISSING DATA: If a field is not present in the document, return null. NEVER \
guess or fabricate a value to fill a gap.

5. Call `extract_asset_portfolio` for assets and `extract_obligations` for \
commercial obligations. Only call the tool(s) for data actually present.\
"""

_PORTFOLIO_INSTRUCTION = (
    "Extract every asset from this portfolio / interconnection document using the "
    "extract_asset_portfolio tool."
)
_CONTRACT_INSTRUCTION = (
    "Extract every commercial obligation from this contract document using the "
    "extract_obligations tool."
)
_COMBINED_INSTRUCTION = (
    "This upload may contain both asset-portfolio data and commercial obligations. "
    "Extract assets with extract_asset_portfolio and obligations with "
    "extract_obligations, calling each tool only if the relevant data is present. "
    "Cross-reference between sections where it improves accuracy."
)

_INSTRUCTIONS: dict[DocType, str] = {
    "portfolio": _PORTFOLIO_INSTRUCTION,
    "contract": _CONTRACT_INSTRUCTION,
    "combined": _COMBINED_INSTRUCTION,
}


def _pdf_document_block(pdf_bytes: bytes) -> dict[str, Any]:
    """Build an Anthropic base64 PDF document content block."""
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
        },
    }


class PortfolioExtractor:
    """Extracts structured assets & obligations from operator-uploaded PDFs."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        # Typed as Any: the SDK's create() params are TypedDicts; we pass plain
        # dict blocks (and tests inject a duck-typed stub), so we keep the call site
        # loose rather than couple to version-specific param type names.
        self._client: Any = client or anthropic.AsyncAnthropic(api_key=get_anthropic_api_key())

    async def _call_claude(
        self, content_blocks: list[dict[str, Any]]
    ) -> ExtractionResult:
        """Single Messages API call; parse tool_use blocks into an ExtractionResult."""
        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=EXTRACTION_TOOLS,
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": content_blocks}],
        )
        return self._parse_response(response)

    async def extract(self, pdf_bytes: bytes, doc_type: DocType) -> ExtractionResult:
        """Extract structured data from a single PDF of the given ``doc_type``."""
        content: list[dict[str, Any]] = [
            _pdf_document_block(pdf_bytes),
            {"type": "text", "text": _INSTRUCTIONS[doc_type]},
        ]
        return await self._call_claude(content)

    async def extract_two_docs(
        self, portfolio_pdf: bytes, contract_pdf: bytes
    ) -> ExtractionResult:
        """Extract from a portfolio PDF and a contract PDF in one cross-referenced call."""
        content: list[dict[str, Any]] = [
            _pdf_document_block(portfolio_pdf),
            _pdf_document_block(contract_pdf),
            {"type": "text", "text": _COMBINED_INSTRUCTION},
        ]
        return await self._call_claude(content)

    # --- response parsing -------------------------------------------------

    def _parse_response(self, response: Any) -> ExtractionResult:
        """Turn a Messages response into an ExtractionResult with flagged fields."""
        assets: list[ExtractedAsset] = []
        obligations: list[ExtractedObligation] = []
        warnings: list[str] = []
        reasoning_parts: list[str] = []

        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                reasoning_parts.append(getattr(block, "text", ""))
            elif block_type == "tool_use":
                name = getattr(block, "name", "")
                data = getattr(block, "input", {}) or {}
                if name == "extract_asset_portfolio":
                    for raw in data.get("assets", []):
                        try:
                            assets.append(ExtractedAsset.model_validate(raw))
                        except Exception as exc:  # noqa: BLE001 - record, don't crash
                            warnings.append(f"Failed to parse asset record: {exc}")
                elif name == "extract_obligations":
                    for raw in data.get("obligations", []):
                        try:
                            obligations.append(ExtractedObligation.model_validate(raw))
                        except Exception as exc:  # noqa: BLE001
                            warnings.append(f"Failed to parse obligation record: {exc}")

        if not assets and not obligations:
            warnings.append("Claude returned no tool calls; no structured data extracted.")

        result = ExtractionResult(
            assets=assets,
            obligations=obligations,
            extraction_warnings=warnings,
            raw_claude_reasoning="\n".join(p for p in reasoning_parts if p) or None,
        )
        result.low_confidence_fields = self._collect_low_confidence(result)
        return result

    @staticmethod
    def _collect_low_confidence(result: ExtractionResult) -> list[dict[str, Any]]:
        """Any asset/obligation below the confidence threshold, flagged for review."""
        flagged: list[dict[str, Any]] = []
        for i, asset in enumerate(result.assets):
            if asset.confidence < CONFIDENCE_THRESHOLD:
                flagged.append(
                    {
                        "kind": "asset",
                        "index": i,
                        "identifier": asset.asset_id,
                        "confidence": asset.confidence,
                        "source_text": asset.source_text,
                        "value": asset.model_dump(),
                    }
                )
        for i, obligation in enumerate(result.obligations):
            if obligation.confidence < CONFIDENCE_THRESHOLD:
                flagged.append(
                    {
                        "kind": "obligation",
                        "index": i,
                        "identifier": obligation.obligation_type,
                        "confidence": obligation.confidence,
                        "source_text": obligation.source_text,
                        "value": obligation.model_dump(),
                    }
                )
        return flagged

    # --- review -----------------------------------------------------------

    @staticmethod
    def build_review(result: ExtractionResult) -> ExtractionReview:
        """Build the human-confirmation view from low-confidence & ambiguous flags."""
        review_items: list[dict[str, Any]] = []

        for flag in result.low_confidence_fields:
            review_items.append(
                {
                    "reason": "low_confidence",
                    "field": f"{flag['kind']}[{flag['identifier']}]",
                    "value": flag.get("value"),
                    "confidence": flag.get("confidence"),
                    "source_text": flag.get("source_text"),
                }
            )

        for i, obligation in enumerate(result.obligations):
            if obligation.ambiguous_language:
                review_items.append(
                    {
                        "reason": "ambiguous_language",
                        "field": f"obligation[{obligation.obligation_type}].ambiguous_language",
                        "value": obligation.ambiguous_language,
                        "confidence": obligation.confidence,
                        "source_text": obligation.source_text,
                        "index": i,
                    }
                )

        return ExtractionReview(
            result=result,
            requires_human_review=bool(review_items),
            review_items=review_items,
        )
