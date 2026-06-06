"""
Email notification sender for VPP alerts, reports, and settlement summaries.

Supports plain text and HTML emails via SMTP with TLS, with
template rendering and attachment support.
"""
from __future__ import annotations

import smtplib
import time
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional


@dataclass
class EmailMessage:
    to: List[str]
    subject: str
    body_text: str
    body_html: Optional[str] = None
    cc: List[str] = field(default_factory=list)
    reply_to: Optional[str] = None


@dataclass
class SMTPConfig:
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True
    from_address: str = "vela@company.com"


ALERT_HTML_TEMPLATE = """
<html><body>
<h2 style="color:{color};">[{severity}] {title}</h2>
<p>{message}</p>
<hr/>
<p><small>Source: {source} | Time: {timestamp}</small></p>
</body></html>
"""


class EmailSender:
    """
    SMTP email client with simulation mode for testing.
    """

    def __init__(self, config: Optional[SMTPConfig] = None, simulation: bool = True) -> None:
        self.config = config or SMTPConfig(host="localhost")
        self.simulation = simulation
        self._sent: List[Dict] = []

    def send(self, message: EmailMessage) -> bool:
        """Send email. In simulation mode, records it instead of transmitting."""
        if self.simulation:
            self._sent.append({
                "to": message.to,
                "subject": message.subject,
                "timestamp": time.time(),
            })
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = message.subject
            msg["From"] = self.config.from_address
            msg["To"] = ", ".join(message.to)
            if message.cc:
                msg["Cc"] = ", ".join(message.cc)

            msg.attach(MIMEText(message.body_text, "plain"))
            if message.body_html:
                msg.attach(MIMEText(message.body_html, "html"))

            with smtplib.SMTP(self.config.host, self.config.port) as server:
                if self.config.use_tls:
                    server.starttls()
                if self.config.username:
                    server.login(self.config.username, self.config.password)
                all_recipients = message.to + message.cc
                server.sendmail(self.config.from_address, all_recipients, msg.as_string())
            return True
        except Exception:
            return False

    def send_alert(
        self,
        recipients: List[str],
        title: str,
        message: str,
        severity: str,
        source: str,
    ) -> bool:
        """Send a formatted alert email."""
        color_map = {"info": "#336699", "warning": "#ff9900", "critical": "#cc3300", "emergency": "#990000"}
        color = color_map.get(severity.lower(), "#333333")
        from datetime import datetime, timezone
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        html = ALERT_HTML_TEMPLATE.format(
            color=color, severity=severity.upper(),
            title=title, message=message, source=source, timestamp=ts
        )
        return self.send(EmailMessage(
            to=recipients,
            subject=f"[Vela VPP] [{severity.upper()}] {title}",
            body_text=f"[{severity.upper()}] {title}\n\n{message}\n\nSource: {source}\nTime: {ts}",
            body_html=html,
        ))
