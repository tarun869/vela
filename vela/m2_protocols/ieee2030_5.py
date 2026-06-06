"""IEEE 2030.5 (Smart Energy Profile 2.0) protocol implementation."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

# IEEE 2030.5 standard port
IEEE2030_5_PORT = 443
IEEE2030_5_NS = "urn:ieee:std:2030.5:ns"


class DERType(IntEnum):
    """DER (Distributed Energy Resource) types per IEEE 2030.5 table 11-66."""
    NOT_APPLICABLE = 0
    VIRTUAL_OR_MIXED = 1
    RECIPROCATING_ENGINE = 2
    FUEL_CELL = 3
    PHOTOVOLTAIC = 4
    COMBINED_HEAT_POWER = 5
    COMBINED_PV_STORAGE = 6
    ELECTRIC_VEHICLE = 7
    FUEL_CELL_STORAGE = 8
    SMALL_WIND = 9
    STORAGE = 80
    OTHER = 90


class DERControlBase(IntEnum):
    """DER control mode bits per IEEE 2030.5."""
    SET_MAX_W = 0x0001
    SET_MAX_VAR = 0x0002
    SET_ES_RANDOM_DELAY = 0x0004
    SET_GRAD_W = 0x0008
    SET_SOFT_GRAD_W = 0x0010
    SET_MAX_CHARGE_RATE_W = 0x0020
    SET_MAX_DISCHARGE_RATE_W = 0x0040
    SET_ES_VOLTAGE_HIGH_TRIP = 0x0080
    SET_ES_VOLTAGE_LOW_TRIP = 0x0100
    SET_ES_FREQUENCY_HIGH_TRIP = 0x0200
    SET_ES_FREQUENCY_LOW_TRIP = 0x0400


@dataclass
class DERSettings:
    """Device-level DER settings per IEEE 2030.5 DERSettings resource."""
    set_max_charge_rate_va: int = 0         # Maximum charge rate in VA
    set_max_discharge_rate_va: int = 0       # Maximum discharge rate in VA
    set_max_w: int = 0                       # Maximum real power in W
    set_max_var: int = 0                     # Maximum reactive power in VAr
    set_min_pf_over_excited_hundredths: int = 9000   # Min PF (lagging)
    set_min_pf_under_excited_hundredths: int = 9000  # Min PF (leading)
    set_es_random_delay: int = 0             # Random delay for smart inverter
    set_grad_w: int = 0                      # Ramp rate in W/s
    set_soft_grad_w: int = 0                 # Soft-start ramp rate in W/s


@dataclass
class DERCapability:
    """DER capability advertisement per IEEE 2030.5."""
    rtg_max_charge_rate_va: int = 0
    rtg_max_discharge_rate_va: int = 0
    rtg_max_w: int = 0
    rtg_max_var: int = 0
    rtg_min_pf_over_excited_hundredths: int = 8000
    rtg_energy_source: DERType = DERType.STORAGE
    type: DERType = DERType.STORAGE


@dataclass
class DERControl:
    """IEEE 2030.5 DER control event."""
    event_id: str
    start_time: int         # Unix timestamp
    duration_seconds: int
    randomize_start: int = 0
    randomize_duration: int = 0
    # Control setpoints
    set_max_w: int | None = None
    set_max_charge_rate_w: int | None = None
    set_max_discharge_rate_w: int | None = None
    set_target_w: int | None = None


@dataclass
class EndDeviceStatus:
    """Status of an IEEE 2030.5 end device (smart inverter / BESS)."""
    lfdi: str               # Long-form device identifier (SHA-256 of cert)
    sfdi: str               # Short-form device identifier (first 36 bits of LFDI)
    device_category: int = 0
    online: bool = True
    last_updated: int = field(default_factory=lambda: int(time.time()))


class IEEE2030_5Client:
    """
    IEEE 2030.5 (SEP 2.0) client for smart inverter and BESS control.

    IEEE 2030.5 is used by CAISO DERO, CPUC Rule 21, and Hawaii Rule 14H
    for utility-side aggregator/DER control.
    """

    def __init__(
        self,
        base_url: str,
        cert_path: str = "",
        key_path: str = "",
        timeout: float = 30.0,
    ) -> None:
        """
        Args:
            base_url: IEEE 2030.5 server base URL (e.g., "https://sep2.utility.com")
            cert_path: Path to client TLS certificate (LFDI derived from this)
            key_path: Path to client private key
            timeout: HTTP request timeout
        """
        self.base_url = base_url.rstrip("/")
        ssl_context = None
        # In production, set up mutual TLS here
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Content-Type": "application/sep+xml",
                "Accept": "application/sep+xml",
            },
            verify=False,  # In production, use proper CA verification
        )
        logger.info("IEEE2030.5 client initialized: %s", base_url)

    async def get_device_capability(self) -> dict[str, str]:
        """Fetch the server DeviceCapability resource (discovery endpoint)."""
        try:
            resp = await self._client.get(f"{self.base_url}/dcap")
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            ns = {"sep": IEEE2030_5_NS}
            return {
                "time_link": root.findtext("sep:TimeLink/sep:href", default="", namespaces=ns) or "",
                "end_device_list_link": root.findtext("sep:EndDeviceListLink/sep:href", default="", namespaces=ns) or "",
                "der_program_list_link": root.findtext("sep:DERProgramListLink/sep:href", default="", namespaces=ns) or "",
            }
        except Exception:
            logger.exception("IEEE 2030.5 DeviceCapability fetch failed")
            return {}

    async def get_end_devices(self) -> list[EndDeviceStatus]:
        """List all registered end devices."""
        devices: list[EndDeviceStatus] = []
        try:
            resp = await self._client.get(f"{self.base_url}/edev")
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            ns = {"sep": IEEE2030_5_NS}
            for ed in root.findall("sep:EndDevice", ns):
                lfdi = ed.findtext("sep:lFDI", default="", namespaces=ns) or ""
                sfdi = ed.findtext("sep:sFDI", default="", namespaces=ns) or ""
                devices.append(EndDeviceStatus(lfdi=lfdi, sfdi=sfdi))
        except Exception:
            logger.exception("IEEE 2030.5 EndDevice list fetch failed")
        return devices

    async def get_der_settings(self, end_device_href: str) -> DERSettings | None:
        """Fetch current DER settings for a specific end device."""
        try:
            resp = await self._client.get(f"{self.base_url}{end_device_href}/der/1/derg")
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            ns = {"sep": IEEE2030_5_NS}

            def get_int(tag: str) -> int:
                text = root.findtext(f"sep:{tag}", default="0", namespaces=ns) or "0"
                return int(text)

            return DERSettings(
                set_max_charge_rate_va=get_int("setMaxChargeRateVA"),
                set_max_discharge_rate_va=get_int("setMaxDischargeRateVA"),
                set_max_w=get_int("setMaxW"),
                set_max_var=get_int("setMaxVar"),
                set_grad_w=get_int("setGradW"),
                set_soft_grad_w=get_int("setSoftGradW"),
            )
        except Exception:
            logger.exception("IEEE 2030.5 DERSettings fetch failed for %s", end_device_href)
            return None

    async def post_der_control(
        self, program_href: str, control: DERControl
    ) -> bool:
        """
        POST a DER control event to the server's DERControlList.

        This is how an aggregator (VPP) sends dispatch setpoints to a fleet
        of IEEE 2030.5-compliant devices.
        """
        # Build the DERControl XML
        ns_str = IEEE2030_5_NS
        xml_parts = [
            f'<DERControl xmlns="{ns_str}">',
            f"  <mRID>{control.event_id}</mRID>",
            f"  <interval>",
            f"    <start>{control.start_time}</start>",
            f"    <duration>{control.duration_seconds}</duration>",
            f"  </interval>",
            f"  <randomizeStart>{control.randomize_start}</randomizeStart>",
            f"  <randomizeDuration>{control.randomize_duration}</randomizeDuration>",
            f"  <DERControlBase>",
        ]
        if control.set_max_w is not None:
            xml_parts.append(f"    <opModMaxLimW>{control.set_max_w}</opModMaxLimW>")
        if control.set_max_charge_rate_w is not None:
            xml_parts.append(
                f"    <opModFixedFlow><value>{control.set_max_charge_rate_w}</value></opModFixedFlow>"
            )
        if control.set_target_w is not None:
            xml_parts.append(
                f"    <opModTargetW><value>{control.set_target_w}</value></opModTargetW>"
            )
        xml_parts.extend(["  </DERControlBase>", "</DERControl>"])
        xml_body = "\n".join(xml_parts)

        try:
            resp = await self._client.post(
                f"{self.base_url}{program_href}/derc",
                content=xml_body.encode("utf-8"),
            )
            return resp.status_code in (200, 201, 204)
        except Exception:
            logger.exception("IEEE 2030.5 DERControl POST failed")
            return False

    async def get_server_time(self) -> int:
        """Fetch current server time (Unix timestamp)."""
        try:
            resp = await self._client.get(f"{self.base_url}/tm")
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            ns = {"sep": IEEE2030_5_NS}
            current_time = root.findtext("sep:currentTime", default="0", namespaces=ns) or "0"
            return int(current_time)
        except Exception:
            logger.exception("IEEE 2030.5 time fetch failed")
            return int(time.time())

    async def close(self) -> None:
        await self._client.aclose()
