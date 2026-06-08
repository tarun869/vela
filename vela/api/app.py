"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vela.api.routers import assets, dispatch, forecasts, market, settlements
from vela.m39_extraction.api import router as extraction_router
from vela.m40_telemetry.api import router as telemetry_router
from vela.m41_optimizer.api import router as dispatch_router
from vela.m42_settlement.api import router as settlement_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Vela VPP API",
        version="0.1.0",
        description="Virtual Power Plant Dispatch Optimization Engine",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(assets.router, prefix="/v1/assets", tags=["assets"])
    app.include_router(dispatch.router, prefix="/v1/dispatch", tags=["dispatch"])
    app.include_router(forecasts.router, prefix="/v1/forecasts", tags=["forecasts"])
    app.include_router(market.router, prefix="/v1/market", tags=["market"])
    app.include_router(settlements.router, prefix="/v1/settlements", tags=["settlements"])
    app.include_router(
        extraction_router, prefix="/api/v1/extraction", tags=["extraction"]
    )
    # Full paths declared on the router (REST + WebSocket) — no prefix.
    app.include_router(telemetry_router, tags=["telemetry"])
    app.include_router(dispatch_router, tags=["dispatch-optimizer"])
    app.include_router(settlement_router, tags=["settlement"])
    return app


app = create_app()
