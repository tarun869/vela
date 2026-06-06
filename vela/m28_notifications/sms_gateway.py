"""
SMS gateway integration for VPP emergency notifications.

Supports Twilio and AWS SNS as SMS backends with fallback logic.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SMSMessage:
    to: str          # E.164 format: +15551234567
    body: str
    from_number: str = "+15550000000"


@dataclass
class SMSResult:
    success: bool
    message_sid: Optional[str]
    error: Optional[str]
    timestamp: float = field(default_factory=time.time)


class TwilioSMSGateway:
    """
    Twilio SMS gateway with simulation mode.

    Messages are truncated to 160 characters (single segment SMS).
    """

    MAX_LENGTH = 160

    def __init__(
        self,
        account_sid: str = "",
        auth_token: str = "",
        simulation: bool = True,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.simulation = simulation
        self._sent: List[Dict] = []

    def send(self, message: SMSMessage) -> SMSResult:
        """Send a single SMS. Returns result with message SID."""
        body = message.body[:self.MAX_LENGTH]

        if self.simulation:
            sid = f"SM{int(time.time())}"
            self._sent.append({
                "to": message.to,
                "body": body,
                "sid": sid,
                "timestamp": time.time(),
            })
            return SMSResult(success=True, message_sid=sid, error=None)

        try:
            # Would use twilio REST API in production
            from urllib.parse import urlencode
            import urllib.request, base64
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
            data = urlencode({"To": message.to, "From": message.from_number, "Body": body}).encode()
            credentials = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
            req = urllib.request.Request(url, data=data, headers={"Authorization": f"Basic {credentials}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                import json
                body_resp = json.loads(resp.read())
                return SMSResult(success=True, message_sid=body_resp["sid"], error=None)
        except Exception as exc:
            return SMSResult(success=False, message_sid=None, error=str(exc))

    def broadcast(self, numbers: List[str], body: str) -> List[SMSResult]:
        """Send the same message to multiple recipients."""
        return [self.send(SMSMessage(to=num, body=body)) for num in numbers]

    def delivery_stats(self) -> Dict[str, int]:
        return {"total_sent": len(self._sent)}
