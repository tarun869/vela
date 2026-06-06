"""WECC (Western Electricity Coordinating Council) EIM connector for LMP."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from vela.m1_ingestion.pipeline import AncillaryPrice, PricePoint

logger = logging.getLogger(__name__)

# CAISO EIM (Energy Imbalance Market) API — covers the WECC footprint
EIM_API = "https://oasis.caiso.com/oasisapi/SingleZip"

# WECC EIM participating balancing authorities
EIM_BAS = [
    "BANC", "AZPS", "BPAT", "CHPD", "DOPD", "EPE", "GCPD", "IID",
    "IPCO", "LDWP", "NWMT", "PACE", "PACW", "PGE", "PSCO", "PSEI",
    "SCL", "SRP", "TIDC", "TPWR", "WACM", "WALC",
]


class WECCConnector:
    """
    Connector for the WECC Energy Imbalance Market (EIM).

    The EIM is a real-time market operated by CAISO on behalf of the
    WECC region. It provides 5-minute interval prices for balancing
    authority areas across the western interconnection.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(timeout=timeout)
        logger.info("WECCConnector initialized")

    async def fetch_lmp(
        self, start: datetime, end: datetime, nodes: list[str]
    ) -> list[PricePoint]:
        """
        Fetch EIM resource price data from CAISO OASIS.

        The EIM uses CAISO's OASIS API with the PRC_INTVL_LMP query
        restricted to EIM balancing authority areas.
        """
        # Default to all EIM BAs if no nodes specified
        target_nodes = nodes if nodes else EIM_BAS[:5]  # limit default scope
        all_results: list[PricePoint] = []

        # Chunk into 24-hour windows to avoid OASIS payload limits
        current = start
        while current < end:
            window_end = min(current + timedelta(hours=24), end)
            try:
                params = {
                    "queryname": "PRC_INTVL_LMP",
                    "startdatetime": current.strftime("%Y%m%dT%H:%M-0000"),
                    "enddatetime": window_end.strftime("%Y%m%dT%H:%M-0000"),
                    "version": 1,
                    "market_run_id": "RTM",
                    "node": ",".join(target_nodes),
                }
                resp = await self._client.get(EIM_API, params=params)
                resp.raise_for_status()
                all_results.extend(self._parse_oasis_lmp(resp.text))
            except httpx.HTTPStatusError as exc:
                logger.warning("WECC/EIM HTTP error: %s", exc.response.status_code)
            except Exception:
                logger.exception("WECC/EIM LMP fetch failed for window %s", current)
            current = window_end

        logger.info("WECC/EIM fetched %d LMP records", len(all_results))
        return all_results

    def _parse_oasis_lmp(self, xml_text: str) -> list[PricePoint]:
        import xml.etree.ElementTree as ET

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
        except Exception:
            logger.warning("WECC OASIS XML parse error")
        return results

    async def fetch_ancillary(
        self, start: datetime, end: datetime
    ) -> list[AncillaryPrice]:
        """
        Fetch WECC EIM ancillary data.

        The EIM itself does not run ancillary markets — those are run by
        individual balancing authorities. This method returns an empty list;
        callers should use the relevant ISO connector (e.g., CAISOConnector)
        for ancillary prices within that BA's footprint.
        """
        logger.debug(
            "WECC EIM does not run ancillary markets; returning empty list. "
            "Use individual BA connectors for AS prices."
        )
        return []

    async def fetch_eim_transfers(
        self, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """
        Fetch EIM inter-BA transfer quantities (shadow prices).

        Returns a list of dicts with keys: timestamp, from_ba, to_ba, mw.
        """
        results: list[dict[str, Any]] = []
        try:
            params = {
                "queryname": "ENE_EIM_TRANSFER_TIE",
                "startdatetime": start.strftime("%Y%m%dT%H:%M-0000"),
                "enddatetime": end.strftime("%Y%m%dT%H:%M-0000"),
                "version": 1,
                "market_run_id": "RTM",
            }
            resp = await self._client.get(EIM_API, params=params)
            resp.raise_for_status()
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)
            ns = {"ns": "http://www.caiso.com/soa/OASISReport_v1.xsd"}
            for row in root.findall(".//ns:REPORT_DATA", ns):
                def get(tag: str) -> str:
                    el = row.find(f"ns:{tag}", ns)
                    return el.text if el is not None and el.text else ""

                try:
                    ts = datetime.fromisoformat(get("INTERVAL_START_GMT")).replace(
                        tzinfo=timezone.utc
                    )
                    results.append({
                        "timestamp": ts,
                        "from_ba": get("FROM_BA"),
                        "to_ba": get("TO_BA"),
                        "mw": float(get("VALUE") or 0),
                    })
                except (ValueError, KeyError):
                    continue
        except Exception:
            logger.exception("WECC EIM transfer fetch failed")
        return results

    async def close(self) -> None:
        await self._client.aclose()
