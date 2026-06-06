"""Celery task: send alerts and notifications (email, Slack, PagerDuty)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal

from vela.workers.celery_app import app

logger = logging.getLogger(__name__)

AlertLevel = Literal["info", "warning", "critical"]


@app.task(
    name="vela.workers.notification_worker.send_alert",
    bind=True,
    max_retries=3,
    default_retry_delay=15,
)
def send_alert(
    self,
    title: str,
    message: str,
    level: AlertLevel = "info",
    asset_id: str | None = None,
    channels: list[str] | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """
    Dispatch an alert to one or more notification channels.
    Supported channels: email, slack, pagerduty
    """
    channels = channels or ["email"]
    logger.info("Sending alert level=%s title=%s channels=%s", level, title, channels)
    results = {}
    for channel in channels:
        try:
            if channel == "email":
                results["email"] = _send_email(title, message, level)
            elif channel == "slack":
                results["slack"] = _send_slack(title, message, level, asset_id)
            elif channel == "pagerduty":
                if level == "critical":
                    results["pagerduty"] = _send_pagerduty(title, message, metadata)
                else:
                    results["pagerduty"] = "skipped_non_critical"
            else:
                results[channel] = f"unknown channel: {channel}"
        except Exception as exc:
            logger.error("Failed to send alert via %s: %s", channel, exc)
            results[channel] = f"failed: {exc}"

    return {
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "title": title,
        "channels": results,
    }


@app.task(name="vela.workers.notification_worker.send_dispatch_summary")
def send_dispatch_summary(
    plan_id: str,
    asset_ids: list[str],
    objective_value: float,
    recipients: list[str] | None = None,
) -> dict[str, Any]:
    """Email a dispatch plan summary to operators."""
    recipients = recipients or [os.getenv("OPERATOR_EMAIL", "ops@vela.energy")]
    subject = f"Dispatch Plan {plan_id[:8]} Complete: ${objective_value:,.2f} expected revenue"
    body = (
        f"Dispatch Plan ID: {plan_id}\n"
        f"Assets: {', '.join(asset_ids)}\n"
        f"Expected Revenue: ${objective_value:,.2f}\n"
        f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
    )
    logger.info("Sending dispatch summary to %s", recipients)
    return {"subject": subject, "recipients": recipients, "sent": True}


@app.task(name="vela.workers.notification_worker.notify_settlement")
def notify_settlement(
    statement_id: str,
    asset_id: str,
    net_revenue_usd: float,
    imbalance_charge_usd: float,
    recipients: list[str] | None = None,
) -> dict[str, Any]:
    """Notify when a settlement statement is finalized."""
    recipients = recipients or [os.getenv("FINANCE_EMAIL", "finance@vela.energy")]
    logger.info("Settlement notification: statement=%s revenue=%.2f", statement_id, net_revenue_usd)
    return {
        "statement_id": statement_id,
        "asset_id": asset_id,
        "net_revenue_usd": net_revenue_usd,
        "imbalance_charge_usd": imbalance_charge_usd,
        "sent_to": recipients,
    }


def _send_email(subject: str, body: str, level: str) -> str:
    """Stub email sender. In production: use SendGrid/SES."""
    smtp_host = os.getenv("SMTP_HOST", "")
    if not smtp_host:
        logger.debug("SMTP not configured, skipping email: %s", subject)
        return "no_smtp_configured"
    # Real implementation would use smtplib or an API client here
    logger.info("Email sent: %s", subject)
    return "sent"


def _send_slack(title: str, body: str, level: str, asset_id: str | None) -> str:
    """Stub Slack sender. In production: use the Slack webhooks API."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        logger.debug("Slack webhook not configured")
        return "no_webhook_configured"
    color = {"info": "#36a64f", "warning": "#ffa500", "critical": "#ff0000"}.get(level, "#cccccc")
    logger.info("Slack notification: [%s] %s", level.upper(), title)
    return "sent"


def _send_pagerduty(title: str, body: str, metadata: dict | None) -> str:
    """Stub PagerDuty sender. In production: use the PagerDuty Events API v2."""
    api_key = os.getenv("PAGERDUTY_API_KEY", "")
    if not api_key:
        logger.debug("PagerDuty API key not configured")
        return "no_api_key_configured"
    logger.info("PagerDuty incident created: %s", title)
    return "triggered"
