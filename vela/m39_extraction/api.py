"""FastAPI router for the PDF portfolio & contract extraction module."""
from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from vela.m4_state.database import ExtractedAssetModel, ObligationModel, get_session

from .extractor import PortfolioExtractor
from .models import ExtractedAsset, ExtractedObligation, ExtractionResult, ExtractionReview

logger = logging.getLogger(__name__)

router = APIRouter()


def get_extractor() -> PortfolioExtractor:
    """Override target in tests; constructed lazily so import never needs a key."""
    return PortfolioExtractor()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        logger.warning("Unparseable date string from extraction: %r", value)
        return None


@router.post("/portfolio", response_model=ExtractionReview)
async def extract_portfolio(
    extractor: Annotated[PortfolioExtractor, Depends(get_extractor)],
    files: list[UploadFile] = File(..., description="One or two PDF files"),
) -> ExtractionReview:
    """Extract assets & obligations from one or two uploaded PDFs.

    Returns an :class:`ExtractionReview` so the frontend knows which fields need
    human confirmation before they are persisted via ``/confirm``.
    """
    if not files or len(files) > 2:
        raise HTTPException(status_code=422, detail="Upload one or two PDF files.")

    payloads: list[bytes] = []
    for f in files:
        if f.content_type not in ("application/pdf", "application/octet-stream", None):
            raise HTTPException(
                status_code=415, detail=f"Unsupported content type: {f.content_type}"
            )
        data = await f.read()
        if not data:
            raise HTTPException(status_code=422, detail=f"Empty file: {f.filename}")
        payloads.append(data)

    try:
        if len(payloads) == 2:
            result = await extractor.extract_two_docs(payloads[0], payloads[1])
        else:
            result = await extractor.extract(payloads[0], doc_type="combined")
    except Exception as exc:  # noqa: BLE001 - surface upstream failures as 502
        logger.exception("Extraction call failed")
        raise HTTPException(status_code=502, detail=f"Extraction failed: {exc}") from exc

    return extractor.build_review(result)


class ConfirmResponse(BaseModel):
    success: bool
    asset_ids: list[int]
    obligation_ids: list[int]


def _asset_to_model(asset: ExtractedAsset) -> ExtractedAssetModel:
    return ExtractedAssetModel(
        asset_id=asset.asset_id,
        asset_type=asset.asset_type,
        rated_mw=asset.rated_mw,
        rated_mwh=asset.rated_mwh,
        iso_node=asset.iso_node,
        qse_name=asset.qse_name,
        chemistry=asset.chemistry,
        warranty_cycles=asset.warranty_cycles,
        warranty_years=asset.warranty_years,
        capacity_guarantee_pct=asset.capacity_guarantee_pct,
        commissioned_date=_parse_date(asset.commissioned_date),
    )


def _obligation_to_model(obligation: ExtractedObligation) -> ObligationModel:
    return ObligationModel(
        obligation_type=obligation.obligation_type,
        committed_mw=obligation.committed_mw,
        delivery_windows=[w.model_dump() for w in obligation.delivery_windows],
        penalty_linear_per_mwh=obligation.penalty_linear_per_mwh,
        penalty_escalation_threshold_mwh=obligation.penalty_escalation_threshold_mwh,
        penalty_escalation_multiplier=obligation.penalty_escalation_multiplier,
        contract_start=_parse_date(obligation.contract_start),
        contract_end=_parse_date(obligation.contract_end),
        extra_metadata={
            "confidence": obligation.confidence,
            "ambiguous_language": obligation.ambiguous_language,
            "source_text": obligation.source_text,
        },
    )


@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_extraction(
    result: ExtractionResult,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConfirmResponse:
    """Persist a human-confirmed extraction result to the database."""
    asset_models = [_asset_to_model(a) for a in result.assets]
    obligation_models = [_obligation_to_model(o) for o in result.obligations]

    session.add_all(asset_models)
    session.add_all(obligation_models)
    await session.commit()

    for m in (*asset_models, *obligation_models):
        await session.refresh(m)

    return ConfirmResponse(
        success=True,
        asset_ids=[m.id for m in asset_models],
        obligation_ids=[m.id for m in obligation_models],
    )
