"""NYISO (New York ISO) API connector for LMP and ancillary prices."""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from vela.m1_ingestion.pipeline import AncillaryPrice, PricePoint

logger = logging.getLogger(__name__)

# NYISO custom reports and market data API
NYISO_REPORTS = "https://mis.nyiso.com/public/csv"
NYISO_API = "https://api.nyiso.com/pub/markets"

# NYISO load zones
NYISO_ZONES = [
    "CAPITL", "CENTRL", "DUNWOD", "GENESE", "H Q", "HUD VL",
    "LONGIL", "MHK VL", "MILLWD", "N.Y.C.", "NORTH", "NPX", "O H",
    "PJM", "WEST",
]


class NYISOConnector:
    """
    Connector for NYISO public market data.

    NYISO provides LMP, ancillary prices, and load data through their
    Market Information System (MIS) and public reporting CSV files.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(timeout=timeout)
        logger.info("NYISOConnector initialized")

    async def fetch_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """
        Fetch real-time 5-minute LMP from NYISO.

        NYISO publishes RT LMP as zipped CSV files per day.
        The zone-level prices are at the 5-minute interval.
        """
        all_results: list[PricePoint] = []
        current = start
        while current < end:
            date_str = current.strftime("%Y%m%d")
            # NYISO RT LMP URL pattern
            url = f"{NYISO_REPORTS}/rtlbmp/{date_str}rtlbmp_zone.csv.zip"
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    for fname in zf.namelist():
                        if fname.endswith(".csv"):
                            with zf.open(fname) as f:
                                reader = csv.DictReader(io.TextIOWrapper(f))
                                for row in reader:
                                    zone = row.get("Zone Name", "").strip()
                                    if nodes and zone not in nodes:
                                        continue
                                    try:
                                        ts_str = row.get("Time Stamp", "")
                                        ts = datetime.strptime(
                                            ts_str, "%m/%d/%Y %H:%M:%S"
                                        ).replace(tzinfo=timezone.utc)
                                        all_results.append(
                                            PricePoint(
                                                timestamp=ts,
                                                lmp=float(row.get("LBMP ($/MWHr)", 0)),
                                                energy=float(
                                                    row.get("Marginal Cost Energy ($/MWHr)", 0)
                                                ),
                                                congestion=float(
                                                    row.get("Marginal Cost Congestion ($/MWHr)", 0)
                                                ),
                                                loss=float(
                                                    row.get("Marginal Cost Losses ($/MWHr)", 0)
                                                ),
                                                node=zone,
                                            )
                                        )
                                    except (ValueError, KeyError):
                                        continue
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "NYISO LMP HTTP error for %s: %s", date_str, exc.response.status_code
                )
            except Exception:
                logger.exception("NYISO LMP fetch failed for %s", date_str)
            current += timedelta(days=1)

        logger.info("NYISO fetched %d LMP records", len(all_results))
        return all_results

    async def fetch_da_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """Fetch NYISO day-ahead LBMP (Location-Based Marginal Pricing)."""
        all_results: list[PricePoint] = []
        current = start
        while current < end:
            date_str = current.strftime("%Y%m%d")
            url = f"{NYISO_REPORTS}/damlbmp/{date_str}damlbmp_zone.csv.zip"
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    for fname in zf.namelist():
                        if fname.endswith(".csv"):
                            with zf.open(fname) as f:
                                reader = csv.DictReader(io.TextIOWrapper(f))
                                for row in reader:
                                    zone = row.get("Zone Name", "").strip()
                                    if nodes and zone not in nodes:
                                        continue
                                    try:
                                        ts_str = row.get("Time Stamp", "")
                                        ts = datetime.strptime(
                                            ts_str, "%m/%d/%Y %H:%M:%S"
                                        ).replace(tzinfo=timezone.utc)
                                        all_results.append(
                                            PricePoint(
                                                timestamp=ts,
                                                lmp=float(row.get("LBMP ($/MWHr)", 0)),
                                                energy=float(
                                                    row.get("Marginal Cost Energy ($/MWHr)", 0)
                                                ),
                                                congestion=float(
                                                    row.get("Marginal Cost Congestion ($/MWHr)", 0)
                                                ),
                                                loss=float(
                                                    row.get("Marginal Cost Losses ($/MWHr)", 0)
                                                ),
                                                node=zone,
                                            )
                                        )
                                    except (ValueError, KeyError):
                                        continue
            except Exception:
                logger.exception("NYISO DA LMP fetch failed for %s", date_str)
            current += timedelta(days=1)
        return all_results

    async def fetch_ancillary(
        self, start: datetime, end: datetime
    ) -> list[AncillaryPrice]:
        """
        Fetch NYISO ancillary service clearing prices.

        NYISO markets: Regulation Reserve, 10-min Spinning, 10-min Non-Spinning,
        30-min Operating Reserve.
        """
        results: list[AncillaryPrice] = []
        current = start
        while current < end:
            date_str = current.strftime("%Y%m%d")
            url = f"{NYISO_REPORTS}/ancillary/{date_str}ancillary_service.csv.zip"
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    for fname in zf.namelist():
                        if fname.endswith(".csv"):
                            with zf.open(fname) as f:
                                reader = csv.DictReader(io.TextIOWrapper(f))
                                for row in reader:
                                    try:
                                        ts_str = row.get("Time Stamp", "")
                                        ts = datetime.strptime(
                                            ts_str, "%m/%d/%Y %H:%M:%S"
                                        ).replace(tzinfo=timezone.utc)
                                        service_type = row.get("Service Type", "").strip().lower()
                                        price = float(row.get("Cost ($/MWHr)", 0))
                                        # Map NYISO service names to standard names
                                        service_map = {
                                            "regulation reserve": "reg_up",
                                            "10 minute spinning": "spin",
                                            "10 minute non-spinning": "nonspin",
                                            "30 minute": "nonspin",
                                        }
                                        for k, v in service_map.items():
                                            if k in service_type:
                                                results.append(
                                                    AncillaryPrice(
                                                        timestamp=ts,
                                                        service=v,
                                                        price=price,
                                                    )
                                                )
                                                break
                                    except (ValueError, KeyError):
                                        continue
            except Exception:
                logger.exception("NYISO ancillary fetch failed for %s", date_str)
            current += timedelta(days=1)
        return results

    async def close(self) -> None:
        await self._client.aclose()
