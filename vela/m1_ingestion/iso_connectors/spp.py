"""SPP (Southwest Power Pool) API connector for LMP and ancillary prices."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from vela.m1_ingestion.pipeline import AncillaryPrice, PricePoint

logger = logging.getLogger(__name__)

# SPP Market Operations Portal API
SPP_MOP = "https://marketplace.spp.org/chart-api"
SPP_PORTAL = "https://portal.spp.org/chart-api/lmp"
SPP_REPORTS = "https://marketplace.spp.org/file-browser-api/download/marketplace-reports"


class SPPConnector:
    """
    Connector for SPP (Southwest Power Pool) market data.

    SPP publishes LMP and ancillary data through their Market Operations Portal.
    LMP is available at 5-minute intervals for all pricing nodes.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Accept": "application/json, text/csv",
                "User-Agent": "Vela-VPP/0.1",
            },
        )
        logger.info("SPPConnector initialized")

    async def fetch_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """
        Fetch SPP real-time LMP at 5-minute intervals.

        SPP uses the LMP endpoint from their Market Operations Portal,
        which provides settlement location prices broken down into
        energy, congestion, and loss components.
        """
        all_results: list[PricePoint] = []
        current = start
        while current < end:
            date_str = current.strftime("%Y%m%d")
            # Try the SPP marketplace CSV endpoint
            url = (
                f"{SPP_REPORTS}/rtbm-lmp-by-location"
                f"?path=%2FRTBM-LMP-BY-LOCATION%2F{current.strftime('%Y/%m')}"
                f"%2FDay{current.strftime('%d')}"
                f"%2FRTBM-LMP-BY-LOCATION-{date_str}0500.csv"
            )
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
                reader = csv.DictReader(io.StringIO(resp.text))
                for row in reader:
                    node_name = row.get("Settlement Location", "").strip()
                    if nodes and node_name not in nodes:
                        continue
                    try:
                        ts_str = f"{row['GMTIntervalEnd']}"
                        ts = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S").replace(
                            tzinfo=timezone.utc
                        )
                        all_results.append(
                            PricePoint(
                                timestamp=ts,
                                lmp=float(row.get("LMP", 0.0)),
                                energy=float(row.get("MLC", 0.0)),
                                congestion=float(row.get("MCC", 0.0)),
                                loss=float(row.get("MEC", 0.0)),
                                node=node_name,
                            )
                        )
                    except (ValueError, KeyError):
                        continue
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "SPP LMP HTTP error for %s: %s", date_str, exc.response.status_code
                )
            except Exception:
                logger.exception("SPP LMP fetch failed for %s", date_str)
            current += timedelta(days=1)

        logger.info("SPP fetched %d LMP records", len(all_results))
        return all_results

    async def fetch_da_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """Fetch SPP day-ahead market (DAM) LMP."""
        all_results: list[PricePoint] = []
        current = start
        while current < end:
            date_str = current.strftime("%Y%m%d")
            url = (
                f"{SPP_REPORTS}/da-lmp-by-location"
                f"?path=%2FDA-LMP-BY-LOCATION%2F{current.strftime('%Y/%m')}"
                f"%2FDay{current.strftime('%d')}"
                f"%2FDA-LMP-BY-LOCATION-{date_str}0100.csv"
            )
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
                reader = csv.DictReader(io.StringIO(resp.text))
                for row in reader:
                    node_name = row.get("Settlement Location", "").strip()
                    if nodes and node_name not in nodes:
                        continue
                    try:
                        ts_str = f"{row['GMTIntervalEnd']}"
                        ts = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S").replace(
                            tzinfo=timezone.utc
                        )
                        all_results.append(
                            PricePoint(
                                timestamp=ts,
                                lmp=float(row.get("LMP", 0.0)),
                                energy=float(row.get("MLC", 0.0)),
                                congestion=float(row.get("MCC", 0.0)),
                                loss=float(row.get("MEC", 0.0)),
                                node=node_name,
                            )
                        )
                    except (ValueError, KeyError):
                        continue
            except Exception:
                logger.exception("SPP DA LMP fetch failed for %s", date_str)
            current += timedelta(days=1)
        return all_results

    async def fetch_ancillary(
        self, start: datetime, end: datetime
    ) -> list[AncillaryPrice]:
        """
        Fetch SPP ancillary service clearing prices.

        SPP markets include Regulation Up, Regulation Down, Spinning Reserve,
        and Supplemental Reserve.
        """
        results: list[AncillaryPrice] = []
        current = start
        while current < end:
            date_str = current.strftime("%Y%m%d")
            url = (
                f"{SPP_REPORTS}/mcp-as"
                f"?path=%2FMCP-AS%2F{current.strftime('%Y/%m')}"
                f"%2FDay{current.strftime('%d')}"
                f"%2FMCP-AS-{date_str}0100.csv"
            )
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
                reader = csv.DictReader(io.StringIO(resp.text))
                for row in reader:
                    try:
                        ts_str = row.get("GMTIntervalEnd", "")
                        ts = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S").replace(
                            tzinfo=timezone.utc
                        )
                        for key, service in [
                            ("Reg Up MCP", "reg_up"),
                            ("Reg Down MCP", "reg_down"),
                            ("Spin MCP", "spin"),
                            ("Supp MCP", "nonspin"),
                        ]:
                            val = row.get(key)
                            if val:
                                results.append(
                                    AncillaryPrice(
                                        timestamp=ts,
                                        service=service,
                                        price=float(val),
                                    )
                                )
                    except (ValueError, KeyError):
                        continue
            except Exception:
                logger.exception("SPP ancillary fetch failed for %s", date_str)
            current += timedelta(days=1)
        return results

    async def close(self) -> None:
        await self._client.aclose()
