"""Tests for m39_extraction — Claude PDF portfolio & contract extraction."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from vela.m39_extraction.extractor import MODEL, PortfolioExtractor
from vela.m39_extraction.models import CONFIDENCE_THRESHOLD, ExtractionResult
from vela.m39_extraction.tools import EXTRACTION_TOOLS

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "sample_portfolio.pdf"


def _tool_use_block(name: str, payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=payload)


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _fake_client(content: list[Any]) -> tuple[Any, AsyncMock]:
    """Return a fake AsyncAnthropic-like client and its messages.create mock."""
    create = AsyncMock(return_value=SimpleNamespace(content=content))
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return client, create


# --- (a) call shape: tools + document block ----------------------------------


async def test_extract_calls_claude_with_tools_and_document_block() -> None:
    client, create = _fake_client([_text_block("done")])
    extractor = PortfolioExtractor(client=client)

    pdf_bytes = b"%PDF-1.4 fake bytes"
    await extractor.extract(pdf_bytes, doc_type="portfolio")

    create.assert_awaited_once()
    kwargs = create.await_args.kwargs

    assert kwargs["model"] == MODEL == "claude-sonnet-4-6"
    assert kwargs["tools"] == EXTRACTION_TOOLS
    assert kwargs["tool_choice"] == {"type": "auto"}

    content = kwargs["messages"][0]["content"]
    doc_block = content[0]
    assert doc_block["type"] == "document"
    assert doc_block["source"]["type"] == "base64"
    assert doc_block["source"]["media_type"] == "application/pdf"
    assert doc_block["source"]["data"] == base64.standard_b64encode(pdf_bytes).decode("ascii")
    assert content[1]["type"] == "text"


async def test_extract_two_docs_passes_both_documents() -> None:
    client, create = _fake_client([_text_block("")])
    extractor = PortfolioExtractor(client=client)

    await extractor.extract_two_docs(b"%PDF-portfolio", b"%PDF-contract")

    content = create.await_args.kwargs["messages"][0]["content"]
    doc_blocks = [b for b in content if b["type"] == "document"]
    assert len(doc_blocks) == 2


# --- (b) result population incl. low_confidence auto-population ---------------


def _two_assets_one_obligation() -> list[Any]:
    return [
        _text_block("Here is my extraction."),
        _tool_use_block(
            "extract_asset_portfolio",
            {
                "assets": [
                    {
                        "asset_id": "BESS-001",
                        "asset_type": "BESS",
                        "rated_mw": 50.0,
                        "rated_mwh": 200.0,
                        "chemistry": "LFP",
                        "confidence": 0.95,
                        "source_text": "BESS-001 is rated at 50 MW / 200 MWh.",
                    },
                    {
                        "asset_id": "SOLAR-014",
                        "asset_type": "Solar",
                        "rated_mw": 25.0,
                        "confidence": 0.60,  # inferred -> low confidence
                        "source_text": "SOLAR-014 is a solar PV plant.",
                    },
                ]
            },
        ),
        _tool_use_block(
            "extract_obligations",
            {
                "obligations": [
                    {
                        "obligation_type": "capacity",
                        "committed_mw": 40.0,
                        "delivery_windows": [
                            {"days": ["Weekdays"], "start_hour": 14, "end_hour": 20}
                        ],
                        "penalty_linear_per_mwh": 150.0,
                        "confidence": 0.92,
                        "source_text": "Seller commits 40 MW of capacity on weekdays.",
                    }
                ]
            },
        ),
    ]


async def test_result_population_and_low_confidence_autopopulation() -> None:
    client, _ = _fake_client(_two_assets_one_obligation())
    extractor = PortfolioExtractor(client=client)

    result = await extractor.extract(b"%PDF", doc_type="combined")

    assert isinstance(result, ExtractionResult)
    assert len(result.assets) == 2
    assert len(result.obligations) == 1
    assert result.assets[0].asset_id == "BESS-001"
    assert result.obligations[0].delivery_windows[0].start_hour == 14
    assert result.raw_claude_reasoning == "Here is my extraction."

    # Only the 0.60-confidence solar asset is flagged.
    assert len(result.low_confidence_fields) == 1
    flagged = result.low_confidence_fields[0]
    assert flagged["kind"] == "asset"
    assert flagged["identifier"] == "SOLAR-014"
    assert flagged["confidence"] < CONFIDENCE_THRESHOLD


async def test_no_tool_calls_records_warning() -> None:
    client, _ = _fake_client([_text_block("I could not read the document.")])
    extractor = PortfolioExtractor(client=client)

    result = await extractor.extract(b"%PDF", doc_type="portfolio")

    assert result.assets == []
    assert result.obligations == []
    assert any("no tool calls" in w.lower() for w in result.extraction_warnings)


# --- (c) low-confidence fields appear in review_items ------------------------


async def test_low_confidence_fields_appear_in_review_items() -> None:
    client, _ = _fake_client(_two_assets_one_obligation())
    extractor = PortfolioExtractor(client=client)
    result = await extractor.extract(b"%PDF", doc_type="combined")

    review = PortfolioExtractor.build_review(result)

    assert review.requires_human_review is True
    low_conf = [it for it in review.review_items if it["reason"] == "low_confidence"]
    assert len(low_conf) == 1
    assert low_conf[0]["field"] == "asset[SOLAR-014]"
    assert low_conf[0]["confidence"] < CONFIDENCE_THRESHOLD


# --- (d) ambiguous_language appears in review_items --------------------------


async def test_ambiguous_language_appears_in_review_items() -> None:
    content = [
        _tool_use_block(
            "extract_obligations",
            {
                "obligations": [
                    {
                        "obligation_type": "capacity",
                        "committed_mw": 40.0,
                        "confidence": 0.95,  # high confidence, but ambiguous clause
                        "ambiguous_language": (
                            "the penalty may be escalated by a factor of up to 2x at "
                            "the buyer's reasonable discretion"
                        ),
                        "source_text": "beyond 100 MWh the penalty may be escalated...",
                    }
                ]
            },
        ),
    ]
    client, _ = _fake_client(content)
    extractor = PortfolioExtractor(client=client)
    result = await extractor.extract(b"%PDF", doc_type="contract")

    review = PortfolioExtractor.build_review(result)

    ambiguous = [it for it in review.review_items if it["reason"] == "ambiguous_language"]
    assert len(ambiguous) == 1
    assert "discretion" in ambiguous[0]["value"]
    assert review.requires_human_review is True


# --- (e) integration test against a real fixture PDF -------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)
async def test_integration_extract_fixture_pdf() -> None:
    assert FIXTURE_PDF.exists(), "sample_portfolio.pdf fixture missing"
    extractor = PortfolioExtractor()  # real client from secrets/env

    result = await extractor.extract(FIXTURE_PDF.read_bytes(), doc_type="combined")

    assert len(result.assets) >= 2
    assert len(result.obligations) >= 1
    asset_ids = {a.asset_id for a in result.assets}
    assert any("BESS" in aid.upper() for aid in asset_ids)
    for asset in result.assets:
        assert 0.0 <= asset.confidence <= 1.0
