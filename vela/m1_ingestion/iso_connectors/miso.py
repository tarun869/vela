"""MISO (Midcontinent ISO) API connector for LMP and ancillary prices."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from vela.m1_ingestion.pipeline import AncillaryPrice, PricePoint

logger = logging.getLogger(__name__)

# MISO API endpoints
MISO_REPORTS_BASE = "https://api.misoenergy.org/MISORTWDDataBroker/DataBrokerServices.asmx"
MISO_MARKET_BASE = "https://api.misoenergy.org/MISORTWDBIReporter/Reporter.asmx"


class MISOConnector:
    """
    Connector for the MISO public market data API.

    MISO publishes LMP, AS prices, and load data through their
    DataBrokerServices and Reporter endpoints. Data is available in
    CSV or JSON format.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        logger.info("MISOConnector initialized")

    async def fetch_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """
        Fetch MISO real-time LMP data (5-minute intervals).

        MISO provides RT LMP at the pricing node level via the
        getLmpConsolidatedTable endpoint.
        """
        all_results: list[PricePoint] = []
        current = start
        while current < end:
            day_str = current.strftime("%Y%m%d")
            try:
                resp = await self._client.get(
                    f"{MISO_REPORTS_BASE}/getLmpConsolidatedTable",
                    params={
                        "reportType": "RT",
                        "startTime": day_str + "T00:00",
                        "endTime": (current + timedelta(days=1)).strftime("%Y%m%d") + "T00:00",
                        "format": "json",
                    },
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()

                for interval in data.get("Intervals", {}).get("Interval", []):
                    ts_str = interval.get("period", "")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S").replace(
                            tzinfo=timezone.utc
                        )
                    except ValueError:
                        continue

                    for node_data in interval.get("PricingNodes", {}).get("PricingNode", []):
                        node_name = node_data.get("name", "MISO.HUB")
                        if nodes and node_name not in nodes:
                            continue
                        try:
                            all_results.append(
                                PricePoint(
                                    timestamp=ts,
                                    lmp=float(node_data.get("LMP", 0.0)),
                                    energy=float(node_data.get("MEC", 0.0)),
                                    congestion=float(node_data.get("MCC", 0.0)),
                                    loss=float(node_data.get("MLC", 0.0)),
                                    node=node_name,
                                )
                            )
                        except (ValueError, KeyError):
                            continue
            except httpx.HTTPStatusError as exc:
                logger.warning("MISO LMP HTTP error for %s: %s", day_str, exc.response.status_code)
            except Exception:
                logger.exception("MISO LMP fetch failed for %s", day_str)
            current += timedelta(days=1)

        logger.info("MISO fetched %d LMP records", len(all_results))
        return all_results

    async def fetch_da_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """Fetch MISO day-ahead LMP from the DA market clearing results."""
        all_results: list[PricePoint] = []
        current = start
        while current < end:
            day_str = current.strftime("%Y%m%d")
            try:
                # MISO DA LMP available as CSV in their archive
                resp = await self._client.get(
                    "https://docs.misoenergy.org/marketreports/"
                    f"{day_str}_da_lmp.csv",
                )
                resp.raise_for_status()
                reader = csv.DictReader(io.StringIO(resp.text))
                for row in reader:
                    node_name = row.get("Node", "")
                    if nodes and node_name not in nodes:
                        continue
                    for hour in range(24):
                        key = f"HE{hour + 1}"
                        if key in row:
                            try:
                                ts = datetime(
                                    current.year, current.month, current.day, hour, 0, 0,
                                    tzinfo=timezone.utc,
                                )
                                all_results.append(
                                    PricePoint(
                                        timestamp=ts,
                                        lmp=float(row[key]),
                                        energy=float(row.get(f"EC_HE{hour + 1}", 0)),
                                        congestion=float(row.get(f"CC_HE{hour + 1}", 0)),
                                        loss=float(row.get(f"LC_HE{hour + 1}", 0)),
                                        node=node_name,
                                    )
                                )
                            except (ValueError, KeyError):
                                continue
            except Exception:
                logger.exception("MISO DA LMP fetch failed for %s", day_str)
            current += timedelta(days=1)
        return all_results

    async def fetch_ancillary(
        self, start: datetime, end: datetime
    ) -> list[AncillaryPrice]:
        """Fetch MISO ancillary service clearing prices (regulation, spin, supplemental)."""
        results: list[AncillaryPrice] = []
        current = start
        while current < end:
            day_str = current.strftime("%Y%m%d")
            try:
                resp = await self._client.get(
                    f"{MISO_MARKET_BASE}/getASMCPResults",
                    params={
                        "startTime": day_str + "T00:00",
                        "endTime": (current + timedelta(days=1)).strftime("%Y%m%d") + "T00:00",
                        "format": "json",
                    },
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                for interval in data.get("data", []):
                    try:
                        ts = datetime.fromisoformat(interval["timestamp"]).replace(
                            tzinfo=timezone.utc
                        )
                        for key, service in [
                            ("RegMCP", "reg_up"),
                            ("SpinMCP", "spin"),
                            ("SupplMCP", "nonspin"),
                        ]:
                            if key in interval:
                                results.append(
                                    AncillaryPrice(
                                        timestamp=ts,
                                        service=service,
                                        price=float(interval[key]),
                                    )
                                )
                    except (ValueError, KeyError):
                        continue
            except Exception:
                logger.exception("MISO ancillary fetch failed for %s", day_str)
            current += timedelta(days=1)
        return results

    async def close(self) -> None:
        await self._client.aclose()
