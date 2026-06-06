"""
Slack notification integration for VPP alerts and operational updates.

Posts formatted messages to Slack channels using incoming webhooks
and Block Kit for rich card formatting.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SlackMessage:
    channel: str
    text: str
    blocks: Optional[List[Dict]] = None
    attachments: Optional[List[Dict]] = None
    username: str = "Vela VPP"
    icon_emoji: str = ":zap:"


def build_alert_blocks(
    title: str,
    message: str,
    severity: str,
    source: str,
    timestamp: float,
) -> List[Dict]:
    """Build Slack Block Kit structure for an operational alert."""
    severity_colors = {
        "info": "#36a64f",
        "warning": "#ffcc00",
        "critical": "#ff6600",
        "emergency": "#cc0000",
    }
    color = severity_colors.get(severity.lower(), "#808080")

    from datetime import datetime, timezone
    ts_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[{severity.upper()}] {title}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message},
            "fields": [
                {"type": "mrkdwn", "text": f"*Source:*\n{source}"},
                {"type": "mrkdwn", "text": f"*Time:*\n{ts_str}"},
            ],
        },
        {"type": "divider"},
    ]


class SlackClient:
    """
    Slack notification client using incoming webhook URL.

    Simulation mode logs messages without making HTTP calls.
    """

    def __init__(self, webhook_url: str = "", simulation_mode: bool = True) -> None:
        self.webhook_url = webhook_url
        self.simulation = simulation_mode
        self._sent_messages: List[SlackMessage] = []

    def send(self, message: SlackMessage) -> bool:
        """
        Send a Slack message via incoming webhook.

        In simulation mode, records message instead of HTTP POST.
        """
        if self.simulation:
            self._sent_messages.append(message)
            return True

        try:
            import urllib.request
            payload = {
                "channel": message.channel,
                "text": message.text,
                "username": message.username,
                "icon_emoji": message.icon_emoji,
            }
            if message.blocks:
                payload["blocks"] = message.blocks
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def send_alert(
        self,
        channel: str,
        title: str,
        message: str,
        severity: str,
        source: str,
    ) -> bool:
        """Convenience method to send a formatted alert card."""
        blocks = build_alert_blocks(title, message, severity, source, time.time())
        msg = SlackMessage(
            channel=channel,
            text=f"[{severity.upper()}] {title}: {message}",
            blocks=blocks,
        )
        return self.send(msg)

    def sent_count(self) -> int:
        return len(self._sent_messages)
