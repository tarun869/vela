"""ISO New England (ISO-NE) API connector for LMP and ancillary prices."""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from vela.m1_ingestion.pipeline import AncillaryPrice, PricePoint

logger = logging.getLogger(__name__)

# ISO-NE Web Services (ISOXML) API
ISONE_API = "https://webservices.iso-ne.com/api/v1.1"


class ISONEConnector:
    """
    Connector for the ISO New England Web Services API.

    ISO-NE requires HTTP Basic Authentication with credentials
    obtained from their registration portal.
    """

    def __init__(
        self,
        username: str = "",
        password: str = "",
        timeout: float = 30.0,
    ) -> None:
        auth = (username, password) if username else None
        self._client = httpx.AsyncClient(
            timeout=timeout,
            auth=auth,
            headers={"Accept": "application/json"},
        )
        logger.info("ISONEConnector initialized")

    async def fetch_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """
        Fetch 5-minute real-time LMP from ISO-NE.

        ISO-NE provides node-level LMPs through their
        /fiveminutelmp/{date} endpoint.
        """
        all_results: list[PricePoint] = []
        current = start
        while current < end:
            date_str = current.strftime("%Y%m%d")
            try:
                resp = await self._client.get(
                    f"{ISONE_API}/fiveminutelmp/{date_str}",
                    params={"format": "json"},
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()

                for record in data.get("FiveMinLmps", {}).get("FiveMinLmp", []):
                    node_name = record.get("Location", {}).get("LocName", "")
                    if nodes and node_name not in nodes:
                        continue
                    try:
                        ts = datetime.fromisoformat(
                            record.get("BeginDate", "").replace("Z", "+00:00")
                        ).replace(tzinfo=timezone.utc)
                        all_results.append(
                            PricePoint(
                                timestamp=ts,
                                lmp=float(record.get("LmpTotal", 0.0)),
                                energy=float(record.get("EnergyComponent", 0.0)),
                                congestion=float(record.get("CongestionComponent", 0.0)),
                                loss=float(record.get("LossComponent", 0.0)),
                                node=node_name,
                            )
                        )
                    except (ValueError, KeyError):
                        continue
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "ISO-NE LMP HTTP error for %s: %s", date_str, exc.response.status_code
                )
            except Exception:
                logger.exception("ISO-NE LMP fetch failed for %s", date_str)
            current += timedelta(days=1)

        logger.info("ISO-NE fetched %d LMP records", len(all_results))
        return all_results

    async def fetch_da_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """Fetch day-ahead hourly LMP from ISO-NE."""
        all_results: list[PricePoint] = []
        current = start
        while current < end:
            date_str = current.strftime("%Y%m%d")
            try:
                resp = await self._client.get(
                    f"{ISONE_API}/hourlylmp/da/final/day/{date_str}",
                    params={"format": "json"},
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                for record in data.get("HourlyLmps", {}).get("HourlyLmp", []):
                    node_name = record.get("Location", {}).get("LocName", "")
                    if nodes and node_name not in nodes:
                        continue
                    try:
                        ts = datetime.fromisoformat(
                            record.get("BeginDate", "").replace("Z", "+00:00")
                        ).replace(tzinfo=timezone.utc)
                        all_results.append(
                            PricePoint(
                                timestamp=ts,
                                lmp=float(record.get("LmpTotal", 0.0)),
                                energy=float(record.get("EnergyComponent", 0.0)),
                                congestion=float(record.get("CongestionComponent", 0.0)),
                                loss=float(record.get("LossComponent", 0.0)),
                                node=node_name,
                            )
                        )
                    except (ValueError, KeyError):
                        continue
            except Exception:
                logger.exception("ISO-NE DA LMP fetch failed for %s", date_str)
            current += timedelta(days=1)
        return all_results

    async def fetch_ancillary(
        self, start: datetime, end: datetime
    ) -> list[AncillaryPrice]:
        """
        Fetch ISO-NE ancillary service clearing prices.

        ISO-NE offers regulation (up/down), 10-minute spinning reserve,
        10-minute non-spinning reserve, and 30-minute reserve products.
        """
        results: list[AncillaryPrice] = []
        current = start
        while current < end:
            date_str = current.strftime("%Y%m%d")
            try:
                resp = await self._client.get(
                    f"{ISONE_API}/ancillaryservices/final/day/{date_str}",
                    params={"format": "json"},
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                for record in data.get("AncillaryServices", {}).get("AncillaryService", []):
                    try:
                        ts = datetime.fromisoformat(
                            record.get("BeginDate", "").replace("Z", "+00:00")
                        ).replace(tzinfo=timezone.utc)
                        for key, service in [
                            ("RegCapClrPrc", "reg_up"),
                            ("RegCapClrPrc", "reg_down"),
                            ("Spin10ClrPrc", "spin"),
                            ("NonSpin10ClrPrc", "nonspin"),
                        ]:
                            val = record.get(key)
                            if val is not None:
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
                logger.exception("ISO-NE ancillary fetch failed for %s", date_str)
            current += timedelta(days=1)
        return results

    async def fetch_load_forecast(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, float]]:
        """Fetch ISO-NE system load forecast."""
        results: list[tuple[datetime, float]] = []
        try:
            date_str = start.strftime("%Y%m%d")
            resp = await self._client.get(
                f"{ISONE_API}/hourlyloadforecast/day/{date_str}",
                params={"format": "json"},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            for record in data.get("HourlyLoadForecasts", {}).get("HourlyLoadForecast", []):
                try:
                    ts = datetime.fromisoformat(
                        record.get("BeginDate", "").replace("Z", "+00:00")
                    ).replace(tzinfo=timezone.utc)
                    results.append((ts, float(record.get("LoadMw", 0.0))))
                except (ValueError, KeyError):
                    continue
        except Exception:
            logger.exception("ISO-NE load forecast fetch failed")
        return results

    async def close(self) -> None:
        await self._client.aclose()
