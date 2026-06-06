"""PJM Data Miner API connector for LMP and ancillary prices."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from vela.m1_ingestion.pipeline import AncillaryPrice, PricePoint

logger = logging.getLogger(__name__)

# PJM Data Miner 2 API base URL
PJM_API = "https://api.pjm.com/api/v1"

# PJM ancillary service product codes
AS_PRODUCT_MAP = {
    "REGULATION": "reg_up",
    "SYNC_RES": "spin",
    "PRIM_RESERVE": "spin",
    "30MIN_RESERVE": "nonspin",
}


class PJMConnector:
    """
    Connector for the PJM Data Miner 2 API.

    Requires an API key from PJM Data Miner portal.
    Covers Day-Ahead and Real-Time LMP, and ancillary markets.
    """

    def __init__(
        self, api_key: str = "", timeout: float = 30.0, market: str = "RT"
    ) -> None:
        """
        Args:
            api_key: PJM Data Miner subscription key.
            timeout: HTTP request timeout in seconds.
            market: "RT" for real-time or "DA" for day-ahead.
        """
        self.market = market.upper()
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Ocp-Apim-Subscription-Key": api_key,
                "Accept": "application/json",
            },
        )
        logger.info("PJMConnector initialized (market=%s)", self.market)

    async def fetch_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """
        Fetch hourly LMP data from PJM for the specified pricing nodes.

        Uses the inst_prce_hrl_cmpnt endpoint for real-time
        or da_hrl_lmps for day-ahead prices.
        """
        endpoint = "da_hrl_lmps" if self.market == "DA" else "rt_unverified_fivemin_lmps"
        all_results: list[PricePoint] = []
        current = start
        while current < end:
            day_end = min(current + timedelta(days=1), end)
            try:
                params: dict[str, Any] = {
                    "startRow": 1,
                    "rowCount": 5000,
                    "datetime_beginning_ept": current.strftime("%Y-%m-%dT%H:%M"),
                    "datetime_ending_ept": day_end.strftime("%Y-%m-%dT%H:%M"),
                    "fields": "datetime_beginning_utc,pnode_id,pnode_name,total_lmp_da,energy,congestion_price,loss_price",
                }
                if nodes:
                    params["pnode_name"] = "|".join(nodes)

                resp = await self._client.get(f"{PJM_API}/{endpoint}", params=params)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                for row in data.get("items", []):
                    try:
                        ts = datetime.fromisoformat(
                            row.get("datetime_beginning_utc", "").replace("Z", "+00:00")
                        ).replace(tzinfo=timezone.utc)
                        all_results.append(
                            PricePoint(
                                timestamp=ts,
                                lmp=float(row.get("total_lmp_da", row.get("total_lmp_rt", 0))),
                                energy=float(row.get("energy", 0)),
                                congestion=float(row.get("congestion_price", 0)),
                                loss=float(row.get("loss_price", 0)),
                                node=row.get("pnode_name", "PSEG"),
                            )
                        )
                    except (ValueError, KeyError):
                        continue
            except httpx.HTTPStatusError as exc:
                logger.warning("PJM LMP HTTP error: %s", exc.response.status_code)
            except Exception:
                logger.exception("PJM LMP fetch failed for %s", current.date())
            current = day_end
        logger.info("PJM fetched %d LMP records", len(all_results))
        return all_results

    async def fetch_ancillary(
        self, start: datetime, end: datetime
    ) -> list[AncillaryPrice]:
        """Fetch regulation and synchronized reserve clearing prices from PJM."""
        results: list[AncillaryPrice] = []
        try:
            resp = await self._client.get(
                f"{PJM_API}/reg_market_results",
                params={
                    "startRow": 1,
                    "rowCount": 2000,
                    "datetime_beginning_ept": start.strftime("%Y-%m-%dT%H:%M"),
                    "datetime_ending_ept": end.strftime("%Y-%m-%dT%H:%M"),
                    "fields": "datetime_beginning_utc,mcp_reg,mcp_reg_up,mcp_reg_down,mcp_spin",
                },
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            for row in data.get("items", []):
                try:
                    ts = datetime.fromisoformat(
                        row.get("datetime_beginning_utc", "").replace("Z", "+00:00")
                    ).replace(tzinfo=timezone.utc)
                    for key, service in [
                        ("mcp_reg_up", "reg_up"),
                        ("mcp_reg_down", "reg_down"),
                        ("mcp_spin", "spin"),
                    ]:
                        if key in row:
                            results.append(
                                AncillaryPrice(
                                    timestamp=ts,
                                    service=service,
                                    price=float(row[key]),
                                )
                            )
                except (ValueError, KeyError):
                    continue
        except Exception:
            logger.exception("PJM ancillary fetch failed")
        return results

    async def fetch_load_forecast(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, float]]:
        """Fetch PJM load forecast from the area_control_error endpoint."""
        results: list[tuple[datetime, float]] = []
        try:
            resp = await self._client.get(
                f"{PJM_API}/load_frcstd_7_day",
                params={
                    "startRow": 1,
                    "rowCount": 1000,
                    "forecast_datetime_beginning_ept": start.strftime("%Y-%m-%dT%H:%M"),
                    "forecast_datetime_ending_ept": end.strftime("%Y-%m-%dT%H:%M"),
                },
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            for row in data.get("items", []):
                try:
                    ts = datetime.fromisoformat(
                        row.get("forecast_datetime_beginning_utc", "").replace("Z", "+00:00")
                    ).replace(tzinfo=timezone.utc)
                    results.append((ts, float(row.get("forecast_load_mw", 0))))
                except (ValueError, KeyError):
                    continue
        except Exception:
            logger.exception("PJM load forecast fetch failed")
        return results

    async def close(self) -> None:
        await self._client.aclose()
