"""CAISO OASIS connector for LMP and ancillary prices."""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from vela.m1_ingestion.pipeline import AncillaryPrice, PricePoint

logger = logging.getLogger(__name__)

OASIS_BASE = "https://oasis.caiso.com/oasisapi/SingleZip"

# CAISO ancillary service product names
AS_PRODUCTS = {
    "REGUP": "reg_up",
    "REGDN": "reg_down",
    "SPIN": "spin",
    "NONSPIN": "nonspin",
}


class CAISOConnector:
    """Connector for the CAISO OASIS public API."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(timeout=timeout)
        logger.info("CAISOConnector initialized")

    async def fetch_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """Fetch interval LMP data from CAISO OASIS for the given nodes and time range."""
        params = {
            "queryname": "PRC_INTVL_LMP",
            "startdatetime": start.strftime("%Y%m%dT%H:%M-0000"),
            "enddatetime": end.strftime("%Y%m%dT%H:%M-0000"),
            "version": 1,
            "market_run_id": "RTM",
            "node": ",".join(nodes) if nodes else "TH_NP15_GEN-APND",
        }
        try:
            resp = await self._client.get(OASIS_BASE, params=params)
            resp.raise_for_status()
            return self._parse_lmp(resp.text)
        except httpx.HTTPStatusError as exc:
            logger.warning("CAISO LMP HTTP error: %s", exc.response.status_code)
            return []
        except Exception:
            logger.exception("CAISO LMP fetch failed")
            return []

    def _parse_lmp(self, xml_text: str) -> list[PricePoint]:
        results: list[PricePoint] = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"ns": "http://www.caiso.com/soa/OASISReport_v1.xsd"}
            for row in root.findall(".//ns:REPORT_DATA", ns):
                def get(tag: str) -> str:
                    el = row.find(f"ns:{tag}", ns)
                    return el.text if el is not None and el.text else "0"

                try:
                    ts = datetime.fromisoformat(get("INTERVAL_START_GMT")).replace(
                        tzinfo=timezone.utc
                    )
                    results.append(
                        PricePoint(
                            timestamp=ts,
                            lmp=float(get("VALUE")),
                            energy=float(get("MW_ENE")),
                            congestion=float(get("MW_CONG")),
                            loss=float(get("MW_LOSS")),
                            node=get("NODE"),
                        )
                    )
                except (ValueError, KeyError):
                    continue
        except ET.ParseError:
            logger.warning("CAISO XML parse error")
        return results

    async def fetch_ancillary(
        self, start: datetime, end: datetime
    ) -> list[AncillaryPrice]:
        """Fetch ancillary service clearing prices from CAISO OASIS."""
        params = {
            "queryname": "PRC_AS",
            "startdatetime": start.strftime("%Y%m%dT%H:%M-0000"),
            "enddatetime": end.strftime("%Y%m%dT%H:%M-0000"),
            "version": 1,
            "market_run_id": "DAM",
            "anc_type": "ALL",
            "anc_region": "CA",
        }
        try:
            resp = await self._client.get(OASIS_BASE, params=params)
            resp.raise_for_status()
            return self._parse_ancillary(resp.text)
        except Exception:
            logger.exception("CAISO ancillary fetch failed")
            return []

    def _parse_ancillary(self, xml_text: str) -> list[AncillaryPrice]:
        results: list[AncillaryPrice] = []
        try:
            root = ET.fromstring(xml_text)
            ns = {"ns": "http://www.caiso.com/soa/OASISReport_v1.xsd"}
            for row in root.findall(".//ns:REPORT_DATA", ns):
                def get(tag: str) -> str:
                    el = row.find(f"ns:{tag}", ns)
                    return el.text if el is not None and el.text else "0"

                product = get("ANC_TYPE")
                service = AS_PRODUCTS.get(product)
                if service is None:
                    continue
                try:
                    ts = datetime.fromisoformat(get("INTERVAL_START_GMT")).replace(
                        tzinfo=timezone.utc
                    )
                    results.append(
                        AncillaryPrice(
                            timestamp=ts,
                            service=service,
                            price=float(get("VALUE")),
                        )
                    )
                except (ValueError, KeyError):
                    continue
        except ET.ParseError:
            logger.warning("CAISO ancillary XML parse error")
        return results

    async def fetch_system_load(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, float]]:
        """Fetch CAISO system-wide load (OASIS ENE_SLRS query)."""
        params = {
            "queryname": "SLD_FCST",
            "startdatetime": start.strftime("%Y%m%dT%H:%M-0000"),
            "enddatetime": end.strftime("%Y%m%dT%H:%M-0000"),
            "version": 1,
            "market_run_id": "DAM",
        }
        try:
            resp = await self._client.get(OASIS_BASE, params=params)
            resp.raise_for_status()
            results: list[tuple[datetime, float]] = []
            root = ET.fromstring(resp.text)
            ns = {"ns": "http://www.caiso.com/soa/OASISReport_v1.xsd"}
            for row in root.findall(".//ns:REPORT_DATA", ns):
                def get(tag: str) -> str:
                    el = row.find(f"ns:{tag}", ns)
                    return el.text if el is not None and el.text else "0"
                ts = datetime.fromisoformat(get("INTERVAL_START_GMT")).replace(tzinfo=timezone.utc)
                results.append((ts, float(get("VALUE"))))
            return results
        except Exception:
            logger.exception("CAISO system load fetch failed")
            return []

    async def close(self) -> None:
        await self._client.aclose()
