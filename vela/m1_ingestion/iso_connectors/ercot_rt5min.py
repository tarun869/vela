"""ERCOT real-time 5-minute interval price connector (SCED dispatch)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from vela.m1_ingestion.pipeline import AncillaryPrice, PricePoint

logger = logging.getLogger(__name__)

ERCOT_API = "https://api.ercot.com/api/public-reports"

# 5-min SCED interval in minutes
SCED_INTERVAL_MIN = 5


class ERCOTRt5minConnector:
    """
    Connector for ERCOT 5-minute real-time prices derived from SCED
    (Security-Constrained Economic Dispatch) results.

    Provides LMPs at every 5-minute SCED execution interval, which are
    used for real-time settlement and dispatch control signals.
    """

    def __init__(self, api_key: str = "", timeout: float = 30.0) -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["Ocp-Apim-Subscription-Key"] = api_key
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)
        logger.info("ERCOTRt5minConnector initialized")

    async def fetch_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """
        Fetch 5-minute SCED LMPs for the given nodes and date range.

        The ERCOT RTD (Real-Time Dispatch) endpoint provides 5-min prices
        for settlement point nodes, hubs, and load zones.
        """
        all_results: list[PricePoint] = []
        # Paginate by day to stay within API size limits
        current = start
        while current < end:
            day_end = min(current + timedelta(days=1), end)
            try:
                resp = await self._client.get(
                    f"{ERCOT_API}/np6-788-cd/rtd_lmp_node_zone_hub",
                    params={
                        "deliveryDateFrom": current.strftime("%Y-%m-%d"),
                        "deliveryDateTo": day_end.strftime("%Y-%m-%d"),
                        "size": 10000,
                    },
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                for row in data.get("data", []):
                    node_name = row.get("settlementPointName", "HB_NORTH")
                    if nodes and node_name not in nodes:
                        continue
                    try:
                        ts = datetime.fromisoformat(row["SCEDTimestamp"]).replace(
                            tzinfo=timezone.utc
                        )
                        all_results.append(
                            PricePoint(
                                timestamp=ts,
                                lmp=float(row.get("LMP", 0.0)),
                                energy=float(row.get("energyLMP", 0.0)),
                                congestion=float(row.get("congestionComponent", 0.0)),
                                loss=float(row.get("lossComponent", 0.0)),
                                node=node_name,
                            )
                        )
                    except (ValueError, KeyError):
                        continue
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "ERCOT RT5min HTTP error for %s: %s",
                    current.date(),
                    exc.response.status_code,
                )
            except Exception:
                logger.exception("ERCOT RT5min fetch failed for %s", current.date())
            current = day_end

        logger.info(
            "ERCOTRt5min: fetched %d 5-min LMP records [%s → %s]",
            len(all_results),
            start.date(),
            end.date(),
        )
        return all_results

    async def fetch_ancillary(
        self, start: datetime, end: datetime
    ) -> list[AncillaryPrice]:
        """
        Fetch real-time ancillary service prices from ERCOT.

        ERCOT publishes real-time AS prices in the Operating Reserve Demand
        Curve (ORDC) adder and ECRS pricing results.
        """
        results: list[AncillaryPrice] = []
        try:
            resp = await self._client.get(
                f"{ERCOT_API}/np6-86-cd/rtsys_lambda",
                params={
                    "deliveryDateFrom": start.strftime("%Y-%m-%d"),
                    "deliveryDateTo": end.strftime("%Y-%m-%d"),
                    "size": 10000,
                },
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            for row in data.get("data", []):
                try:
                    ts = datetime.fromisoformat(row["SCEDTimestamp"]).replace(tzinfo=timezone.utc)
                    # ORDC adder is effectively the real-time spinning reserve price
                    ordc_adder = float(row.get("ORDCAdder", 0.0))
                    if ordc_adder > 0:
                        results.append(
                            AncillaryPrice(timestamp=ts, service="spin", price=ordc_adder)
                        )
                    # RRS and NSRS availability payments
                    for key, service in [("RRS", "spin"), ("NSRS", "nonspin")]:
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
            logger.exception("ERCOT RT ancillary fetch failed")
        return results

    async def fetch_latest_sced_interval(self, nodes: list[str]) -> list[PricePoint]:
        """
        Fetch the single most-recent 5-min SCED interval.

        Used for real-time dispatch control loops that need sub-minute latency.
        """
        now = datetime.now(timezone.utc)
        # Round down to nearest 5 minutes
        rounded = now.replace(
            minute=(now.minute // SCED_INTERVAL_MIN) * SCED_INTERVAL_MIN,
            second=0,
            microsecond=0,
        )
        window_start = rounded - timedelta(minutes=SCED_INTERVAL_MIN * 2)
        prices = await self.fetch_lmp(window_start, now, nodes)
        # Return only the latest interval
        if not prices:
            return []
        latest_ts = max(p.timestamp for p in prices)
        return [p for p in prices if p.timestamp == latest_ts]

    async def close(self) -> None:
        await self._client.aclose()
