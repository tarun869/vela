"""ERCOT API connector for real-time LMP and AS prices."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from vela.m1_ingestion.pipeline import AncillaryPrice, PricePoint

logger = logging.getLogger(__name__)

ERCOT_API = "https://api.ercot.com/api/public-reports"

# ERCOT ancillary service keys in API response
AS_KEYS = {
    "regUp": "reg_up",
    "regDown": "reg_down",
    "rrs": "spin",
    "ecrs": "nonspin",
    "nsrs": "nonspin_supplemental",
}


class ERCOTConnector:
    """Connector for the ERCOT Public API (v2)."""

    def __init__(self, api_key: str = "", timeout: float = 30.0) -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["Ocp-Apim-Subscription-Key"] = api_key
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)
        logger.info("ERCOTConnector initialized")

    async def fetch_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """Fetch settlement point prices (SPPs) from ERCOT DAM."""
        try:
            resp = await self._client.get(
                f"{ERCOT_API}/np6-905-cd/spp_node_zone_hub",
                params={
                    "deliveryDateFrom": start.strftime("%Y-%m-%d"),
                    "deliveryDateTo": end.strftime("%Y-%m-%d"),
                    "size": 1000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results: list[PricePoint] = []
            for row in data.get("data", []):
                # Filter by requested nodes if provided
                node_name = row.get("settlementPointName", "HB_NORTH")
                if nodes and node_name not in nodes:
                    continue
                try:
                    ts_str = f"{row['deliveryDate']}T{int(row.get('deliveryHour', 0)) - 1:02d}:00:00"
                    ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                    results.append(
                        PricePoint(
                            timestamp=ts,
                            lmp=float(row.get("settlementPointPrice", 0)),
                            energy=float(row.get("settlementPointPrice", 0)),
                            congestion=0.0,
                            loss=0.0,
                            node=node_name,
                        )
                    )
                except (ValueError, KeyError):
                    continue
            return results
        except httpx.HTTPStatusError as exc:
            logger.warning("ERCOT LMP HTTP error: %s", exc.response.status_code)
            return []
        except Exception:
            logger.exception("ERCOT LMP fetch failed")
            return []

    async def fetch_rt_spp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """Fetch real-time settlement point prices (15-min intervals)."""
        try:
            resp = await self._client.get(
                f"{ERCOT_API}/np6-788-cd/rtd_lmp_node_zone_hub",
                params={
                    "deliveryDateFrom": start.strftime("%Y-%m-%d"),
                    "deliveryDateTo": end.strftime("%Y-%m-%d"),
                    "size": 5000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results: list[PricePoint] = []
            for row in data.get("data", []):
                node_name = row.get("settlementPointName", "HB_NORTH")
                if nodes and node_name not in nodes:
                    continue
                try:
                    ts = datetime.fromisoformat(row["SCEDTimestamp"]).replace(tzinfo=timezone.utc)
                    results.append(
                        PricePoint(
                            timestamp=ts,
                            lmp=float(row.get("LMP", 0)),
                            energy=float(row.get("energyOnlyOfferCap", 0)),
                            congestion=float(row.get("congestionComponent", 0)),
                            loss=float(row.get("lossComponent", 0)),
                            node=node_name,
                        )
                    )
                except (ValueError, KeyError):
                    continue
            return results
        except Exception:
            logger.exception("ERCOT RT SPP fetch failed")
            return []

    async def fetch_ancillary(
        self, start: datetime, end: datetime
    ) -> list[AncillaryPrice]:
        """Fetch DAM ancillary service clearing prices from ERCOT."""
        try:
            resp = await self._client.get(
                f"{ERCOT_API}/np3-911-er/dam_stlmnt_pnt_prices",
                params={
                    "deliveryDateFrom": start.strftime("%Y-%m-%d"),
                    "deliveryDateTo": end.strftime("%Y-%m-%d"),
                    "size": 1000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results: list[AncillaryPrice] = []
            for row in data.get("data", []):
                try:
                    ts_str = f"{row['deliveryDate']}T{int(row.get('deliveryHour', 0)) - 1:02d}:00:00"
                    ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                    for api_key, service in AS_KEYS.items():
                        if api_key in row:
                            results.append(
                                AncillaryPrice(
                                    timestamp=ts,
                                    service=service,
                                    price=float(row[api_key]),
                                )
                            )
                except (ValueError, KeyError):
                    continue
            return results
        except Exception:
            logger.exception("ERCOT ancillary fetch failed")
            return []

    async def fetch_load_forecast(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, float]]:
        """Fetch ERCOT short-term load forecast (STLF)."""
        try:
            resp = await self._client.get(
                f"{ERCOT_API}/np3-566-cd/lf_by_model_weather_zone",
                params={
                    "deliveryDateFrom": start.strftime("%Y-%m-%d"),
                    "deliveryDateTo": end.strftime("%Y-%m-%d"),
                    "size": 2000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            results: list[tuple[datetime, float]] = []
            for row in data.get("data", []):
                try:
                    ts_str = f"{row['deliveryDate']}T{int(row.get('deliveryHour', 0)) - 1:02d}:00:00"
                    ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                    results.append((ts, float(row.get("systemTotal", 0))))
                except (ValueError, KeyError):
                    continue
            return results
        except Exception:
            logger.exception("ERCOT load forecast fetch failed")
            return []

    async def close(self) -> None:
        await self._client.aclose()
