"""OpenADR 2.0b demand response protocol implementation."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

# OpenADR 2.0b namespace
OADR_NS = "http://docs.oasis-open.org/ns/energyinterop/201110"
OADR_PYLD_NS = "http://docs.oasis-open.org/ns/energyinterop/201110/payloads"
EI_NS = "http://docs.oasis-open.org/ns/energyinterop/201110"
EMIX_NS = "http://docs.oasis-open.org/ns/emix/2011/06"
XCAL_NS = "urn:ietf:params:xml:ns:icalendar-2.0"


class SignalType(Enum):
    """OpenADR event signal types."""
    LEVEL = "LEVEL"
    PRICE = "PRICE"
    PRICE_MULTIPLIER = "PRICE_MULTIPLIER"
    PRICE_RELATIVE = "PRICE_RELATIVE"
    DELTA = "DELTA"
    SETPOINT = "SETPOINT"
    X_LOAD_CONTROL_CAPACITY = "x-loadControlCapacity"
    X_LOAD_CONTROL_LEVEL_OFFSET = "x-loadControlLevelOffset"
    X_LOAD_CONTROL_PERCENT_OFFSET = "x-loadControlPercentOffset"
    X_LOAD_CONTROL_SETPOINT = "x-loadControlSetpoint"


class EventStatus(Enum):
    """OpenADR event status."""
    NONE = "none"
    FAR = "far"
    NEAR = "near"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OptType(Enum):
    """VEN opt-in/opt-out status."""
    OPT_IN = "optIn"
    OPT_OUT = "optOut"


@dataclass
class EventInterval:
    duration_seconds: int
    signal_payload: float   # Normalized value (1.0 = normal, 2.0 = high, 3.0 = emergency)
    uid: int = 0


@dataclass
class ADREvent:
    """Represents an OpenADR 2.0b Demand Response event."""
    event_id: str
    modification_number: int
    market_context: str
    created_datetime: str
    dtstart: str                    # ISO 8601 datetime of event start
    duration_seconds: int
    signal_name: str
    signal_type: SignalType
    intervals: list[EventInterval] = field(default_factory=list)
    status: EventStatus = EventStatus.FAR
    response_required: str = "always"  # "always", "never"
    priority: int = 0
    test_event: bool = False

    @property
    def is_emergency(self) -> bool:
        """Check if any interval has emergency-level signal (>=3.0)."""
        return any(i.signal_payload >= 3.0 for i in self.intervals)

    @property
    def max_signal(self) -> float:
        if not self.intervals:
            return 0.0
        return max(i.signal_payload for i in self.intervals)


@dataclass
class EventResponse:
    """VEN response to a DR event."""
    request_id: str
    event_id: str
    modification_number: int
    opt_type: OptType
    ven_id: str
    response_code: int = 200
    response_description: str = "OK"


class OpenADRVEN:
    """
    OpenADR 2.0b Virtual End Node (VEN) client.

    The VEN represents a Vela-managed VPP asset fleet that subscribes to
    demand response events from a Virtual Top Node (VTN — typically a utility
    or ISO demand response aggregator).

    Supports EiRegisterParty, oadrPoll, oadrRequestEvent, oadrCreatedEvent.
    """

    def __init__(
        self,
        vtn_url: str,
        ven_id: str = "",
        ven_name: str = "vela-vpp-ven",
        timeout: float = 30.0,
    ) -> None:
        self.vtn_url = vtn_url.rstrip("/")
        self.ven_id = ven_id or str(uuid.uuid4())
        self.ven_name = ven_name
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Content-Type": "application/xml",
                "Accept": "application/xml",
            },
        )
        self._active_events: dict[str, ADREvent] = {}
        self._event_callbacks: list[Any] = []
        self._registered = False
        logger.info("OpenADR VEN initialized: %s @ %s", ven_id, vtn_url)

    async def register(self) -> bool:
        """
        Register the VEN with the VTN (oadrRegisterReport / EiRegisterParty).
        """
        request_id = str(uuid.uuid4())
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<oadrPayload xmlns="http://openadr.org/oadr-2.0b/2012/07"
             xmlns:ei="{EI_NS}">
  <oadrSignedObject>
    <oadrRegisterReport ei:schemaVersion="2.0b">
      <requestID>{request_id}</requestID>
      <oadrReport>
        <ei:eiReportID>telemetry</ei:eiReportID>
        <oadrReportDescription>
          <ei:rID>resource_status</ei:rID>
          <ei:reportType>x-resourceStatus</ei:reportType>
          <ei:readingType>Direct Read</ei:readingType>
          <ei:marketContext>http://MarketContext1</ei:marketContext>
          <oadrSamplingRate>
            <oadrMinPeriod>PT1M</oadrMinPeriod>
            <oadrMaxPeriod>PT1H</oadrMaxPeriod>
            <oadrOnChange>false</oadrOnChange>
          </oadrSamplingRate>
        </oadrReportDescription>
      </oadrReport>
      <venID>{self.ven_id}</venID>
    </oadrRegisterReport>
  </oadrSignedObject>
</oadrPayload>"""
        try:
            resp = await self._client.post(
                f"{self.vtn_url}/OpenADR2/Simple/2.0b/EiRegisterParty",
                content=xml.encode("utf-8"),
            )
            resp.raise_for_status()
            self._registered = True
            logger.info("OpenADR VEN registered with VTN")
            return True
        except Exception:
            logger.exception("OpenADR registration failed")
            return False

    async def poll(self) -> list[ADREvent]:
        """
        Poll the VTN for pending events (oadrPoll).

        Returns any new or updated DR events.
        """
        request_id = str(uuid.uuid4())
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<oadrPayload xmlns="http://openadr.org/oadr-2.0b/2012/07">
  <oadrSignedObject>
    <oadrPoll>
      <venID>{self.ven_id}</venID>
    </oadrPoll>
  </oadrSignedObject>
</oadrPayload>"""
        try:
            resp = await self._client.post(
                f"{self.vtn_url}/OpenADR2/Simple/2.0b/EiEvent",
                content=xml.encode("utf-8"),
            )
            resp.raise_for_status()
            return self._parse_distribute_event(resp.text)
        except Exception:
            logger.exception("OpenADR poll failed")
            return []

    def _parse_distribute_event(self, xml_text: str) -> list[ADREvent]:
        events: list[ADREvent] = []
        try:
            root = ET.fromstring(xml_text)
            ns = {
                "oadr": "http://openadr.org/oadr-2.0b/2012/07",
                "ei": EI_NS,
                "xcal": XCAL_NS,
            }
            for evt in root.findall(".//ei:event", ns):
                def get(path: str) -> str:
                    el = evt.find(path, ns)
                    return el.text if el is not None and el.text else ""

                event_id = get("ei:eventDescriptor/ei:eventID")
                mod_num = int(get("ei:eventDescriptor/ei:modificationNumber") or "0")
                status_str = get("ei:eventDescriptor/ei:eventStatus")
                try:
                    status = EventStatus(status_str)
                except ValueError:
                    status = EventStatus.NONE

                # Parse intervals
                intervals: list[EventInterval] = []
                for interval in evt.findall(".//ei:intervals/ei:interval", ns):
                    uid = int(interval.findtext("xcal:uid/xcal:integer", default="0", namespaces=ns) or "0")
                    duration_text = interval.findtext(
                        "xcal:duration/xcal:duration-value", default="PT0S", namespaces=ns
                    ) or "PT0S"
                    duration_sec = self._parse_iso_duration(duration_text)
                    signal_val = float(
                        interval.findtext(".//ei:payloadFloat/ei:value", default="1.0", namespaces=ns) or "1.0"
                    )
                    intervals.append(EventInterval(
                        uid=uid,
                        duration_seconds=duration_sec,
                        signal_payload=signal_val,
                    ))

                dtstart = get(".//xcal:dtstart/xcal:date-time")
                total_duration = sum(i.duration_seconds for i in intervals)
                signal_name = get("ei:eiActivePeriod/xcal:properties/ei:tolerance/ei:tolerate/xcal:duration-value") or "SIMPLE"

                adr_event = ADREvent(
                    event_id=event_id,
                    modification_number=mod_num,
                    market_context=get("ei:eventDescriptor/ei:eiMarketContext/ei:marketContext"),
                    created_datetime=get("ei:eventDescriptor/ei:createdDateTime"),
                    dtstart=dtstart,
                    duration_seconds=total_duration,
                    signal_name=signal_name,
                    signal_type=SignalType.LEVEL,
                    intervals=intervals,
                    status=status,
                )
                events.append(adr_event)
                self._active_events[event_id] = adr_event
        except ET.ParseError:
            logger.warning("OpenADR XML parse error")
        return events

    @staticmethod
    def _parse_iso_duration(duration: str) -> int:
        """Parse ISO 8601 duration string to seconds (e.g. PT1H30M -> 5400)."""
        import re
        pattern = re.compile(
            r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
        )
        m = pattern.match(duration)
        if not m:
            return 0
        _, _, days, hours, minutes, seconds = [int(x or 0) for x in m.groups()]
        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    async def opt_in(self, event_id: str) -> bool:
        """Send oadrCreatedEvent opt-in response for an event."""
        return await self._send_event_response(event_id, OptType.OPT_IN)

    async def opt_out(self, event_id: str) -> bool:
        """Send oadrCreatedEvent opt-out response for an event."""
        return await self._send_event_response(event_id, OptType.OPT_OUT)

    async def _send_event_response(
        self, event_id: str, opt_type: OptType
    ) -> bool:
        event = self._active_events.get(event_id)
        if not event:
            return False
        request_id = str(uuid.uuid4())
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<oadrPayload xmlns="http://openadr.org/oadr-2.0b/2012/07"
             xmlns:ei="{EI_NS}">
  <oadrSignedObject>
    <oadrCreatedEvent ei:schemaVersion="2.0b">
      <eiCreatedEvent>
        <ei:eiResponse>
          <ei:responseCode>200</ei:responseCode>
          <ei:responseDescription>OK</ei:responseDescription>
          <requestID>{request_id}</requestID>
        </ei:eiResponse>
        <ei:eventResponses>
          <ei:eventResponse>
            <ei:responseCode>200</ei:responseCode>
            <ei:responseDescription>OK</ei:responseDescription>
            <requestID>{request_id}</requestID>
            <ei:qualifiedEventID>
              <ei:eventID>{event_id}</ei:eventID>
              <ei:modificationNumber>{event.modification_number}</ei:modificationNumber>
            </ei:qualifiedEventID>
            <ei:optType>{opt_type.value}</ei:optType>
          </ei:eventResponse>
        </ei:eventResponses>
        <venID>{self.ven_id}</venID>
      </eiCreatedEvent>
    </oadrCreatedEvent>
  </oadrSignedObject>
</oadrPayload>"""
        try:
            resp = await self._client.post(
                f"{self.vtn_url}/OpenADR2/Simple/2.0b/EiEvent",
                content=xml.encode("utf-8"),
            )
            return resp.status_code in (200, 201, 204)
        except Exception:
            logger.exception("OpenADR event response failed")
            return False

    async def run_polling_loop(self, interval_seconds: int = 60) -> None:
        """Continuously poll for DR events and fire registered callbacks."""
        logger.info("OpenADR polling loop started (interval=%ds)", interval_seconds)
        while True:
            events = await self.poll()
            for event in events:
                for cb in self._event_callbacks:
                    try:
                        cb(event)
                    except Exception:
                        logger.exception("OpenADR event callback error")
            await asyncio.sleep(interval_seconds)

    def on_event(self, callback: Any) -> None:
        """Register a callback invoked when a new DR event is received."""
        self._event_callbacks.append(callback)

    @property
    def active_events(self) -> list[ADREvent]:
        return [
            e for e in self._active_events.values()
            if e.status in (EventStatus.NEAR, EventStatus.ACTIVE)
        ]

    async def close(self) -> None:
        await self._client.aclose()
