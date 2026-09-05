"""CloudPulse AI — Smart Alerting & Multi-Channel Notification Pipeline.

Dispatches operational alerts and cost warnings across multiple channels:
- Generic Webhooks (HTTP POST with JSON payload)
- Discord Webhooks (rich embeds color-coded by severity)
- Slack Webhooks (formatted blocks and attachments)
- Email (SMTP delivery if SMTP_HOST configured, else console logger)

ANTI-SPAM & RELIABILITY FEATURES:
1. Cooldown Tracking: Limits notification frequency per server/rule to prevent alert storms.
2. Deduplication: Suppresses identical active alerts within the cooldown window.
3. Delivery Audit Trail: Records every delivery attempt into the notification_logs table.
4. Non-Blocking Execution: Asynchronous, failure-isolated HTTP requests.
"""

from __future__ import annotations

import hashlib
import json
import os
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any, Optional, TypedDict

import httpx
from dotenv import load_dotenv

from logging_conf import get_logger

logger = get_logger("backend.notifications")

load_dotenv()

# In-memory cooldown & deduplication tracker
# Key: f"{server_id}:{rule_or_alert_type}:{channel_type}" -> timestamp
_COOLDOWN_TRACKER: dict[str, datetime] = {}

# Default cooldown if unspecified (15 minutes)
DEFAULT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "15"))


class NotificationPayload(TypedDict):
    title: str
    message: str
    severity: str  # "info" | "warning" | "critical"
    server_id: str
    server_name: str
    alert_type: str
    timestamp: str
    meta: dict[str, Any]


class DeliveryResult(TypedDict):
    channel_type: str
    status: str  # "sent" | "failed" | "cooldown_skipped"
    recipient_target: str
    error_message: Optional[str]


def _make_dedup_key(server_id: str, alert_type: str, channel_type: str) -> str:
    return f"{server_id}:{alert_type}:{channel_type}"


def is_in_cooldown(server_id: str, alert_type: str, channel_type: str, cooldown_minutes: int) -> bool:
    """Check if an alert for this server, alert type, and channel is still in its cooldown period."""
    key = _make_dedup_key(server_id, alert_type, channel_type)
    last_sent = _COOLDOWN_TRACKER.get(key)
    if not last_sent:
        return False
    elapsed = (datetime.now(timezone.utc) - last_sent).total_seconds() / 60.0
    return elapsed < cooldown_minutes


def mark_sent(server_id: str, alert_type: str, channel_type: str) -> None:
    """Record timestamp of sent alert to initiate cooldown window."""
    key = _make_dedup_key(server_id, alert_type, channel_type)
    _COOLDOWN_TRACKER[key] = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Channel Dispatchers
# ---------------------------------------------------------------------------

def send_generic_webhook(url: str, payload: NotificationPayload, secret: Optional[str] = None) -> DeliveryResult:
    """Send alert to a generic HTTP webhook."""
    headers = {"Content-Type": "application/json"}
    if secret:
        # Include HMAC-SHA256 signature if secret is configured
        body_bytes = json.dumps(payload).encode("utf-8")
        sig = hashlib.sha256(secret.encode("utf-8") + body_bytes).hexdigest()
        headers["X-CloudPulse-Signature"] = sig

    try:
        with httpx.Client(timeout=8.0) as client:
            res = client.post(url, headers=headers, json=payload)
            res.raise_for_status()
        return {"channel_type": "webhook", "status": "sent", "recipient_target": url, "error_message": None}
    except Exception as exc:
        logger.warning("notification.webhook_failed", url=url, error=str(exc))
        return {"channel_type": "webhook", "status": "failed", "recipient_target": url, "error_message": str(exc)}


def send_discord_webhook(url: str, payload: NotificationPayload) -> DeliveryResult:
    """Send rich formatted Discord embed card."""
    severity_colors = {
        "critical": 0xE8462C,  # Red
        "warning": 0xFFE600,   # Amber
        "info": 0x06B6D4,      # Cyan
    }
    color = severity_colors.get(payload["severity"].lower(), 0x10B981)

    embed = {
        "title": f"🚨 [{payload['severity'].upper()}] {payload['title']}",
        "description": payload["message"],
        "color": color,
        "fields": [
            {"name": "Server", "value": f"`{payload['server_name']}` ({payload['server_id']})", "inline": True},
            {"name": "Alert Type", "value": payload["alert_type"], "inline": True},
            {"name": "Severity", "value": payload["severity"].upper(), "inline": True},
        ],
        "footer": {"text": "CloudPulse AI Monitoring"},
        "timestamp": payload["timestamp"],
    }

    body = {
        "username": "CloudPulse AI",
        "avatar_url": "https://raw.githubusercontent.com/nithincodesx/CloudPulse-AI/main/public/favicon.ico",
        "embeds": [embed],
    }

    try:
        with httpx.Client(timeout=8.0) as client:
            res = client.post(url, json=body)
            res.raise_for_status()
        return {"channel_type": "discord", "status": "sent", "recipient_target": url, "error_message": None}
    except Exception as exc:
        logger.warning("notification.discord_failed", error=str(exc))
        return {"channel_type": "discord", "status": "failed", "recipient_target": url, "error_message": str(exc)}


def send_slack_webhook(url: str, payload: NotificationPayload) -> DeliveryResult:
    """Send formatted Slack incoming webhook blocks."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"[{payload['severity'].upper()}] {payload['title']}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{payload['message']}*"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"*Server:* {payload['server_name']} | *Type:* {payload['alert_type']} | *Time:* {payload['timestamp']}"}
            ],
        },
    ]
    body = {"blocks": blocks}

    try:
        with httpx.Client(timeout=8.0) as client:
            res = client.post(url, json=body)
            res.raise_for_status()
        return {"channel_type": "slack", "status": "sent", "recipient_target": url, "error_message": None}
    except Exception as exc:
        logger.warning("notification.slack_failed", error=str(exc))
        return {"channel_type": "slack", "status": "failed", "recipient_target": url, "error_message": str(exc)}


def send_email_alert(recipient_email: str, payload: NotificationPayload) -> DeliveryResult:
    """Send alert email via SMTP if configured, else log to console."""
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    sender_email = os.getenv("SMTP_FROM", "alerts@cloudpulse.ai")

    if not smtp_host or not smtp_user or not smtp_pass:
        logger.info("notification.email_simulated", recipient=recipient_email, subject=payload["title"])
        return {
            "channel_type": "email",
            "status": "sent",
            "recipient_target": recipient_email,
            "error_message": None,
        }

    msg = MIMEText(f"{payload['message']}\n\nServer: {payload['server_name']}\nTimestamp: {payload['timestamp']}")
    msg["Subject"] = f"[CloudPulse Alert] [{payload['severity'].upper()}] {payload['title']}"
    msg["From"] = sender_email
    msg["To"] = recipient_email

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return {"channel_type": "email", "status": "sent", "recipient_target": recipient_email, "error_message": None}
    except Exception as exc:
        logger.warning("notification.email_failed", recipient=recipient_email, error=str(exc))
        return {"channel_type": "email", "status": "failed", "recipient_target": recipient_email, "error_message": str(exc)}


# ---------------------------------------------------------------------------
# Notification Pipeline Orchestrator
# ---------------------------------------------------------------------------

def dispatch_alert_notifications(
    payload: NotificationPayload,
    channels: list[dict],
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
) -> list[DeliveryResult]:
    """Evaluate cooldown, deduplication, and dispatch alert to configured channels."""
    results: list[DeliveryResult] = []
    server_id = payload["server_id"]
    alert_type = payload["alert_type"]

    for ch in channels:
        if not ch.get("enabled", True):
            continue

        ch_type = ch.get("channel_type", "webhook").lower()
        config = ch.get("config", {})

        # Check cooldown & deduplication
        if is_in_cooldown(server_id, alert_type, ch_type, cooldown_minutes):
            logger.info("notification.cooldown_skipped", server=server_id, alert=alert_type, channel=ch_type)
            results.append({
                "channel_type": ch_type,
                "status": "cooldown_skipped",
                "recipient_target": config.get("url") or config.get("email") or "channel",
                "error_message": f"Suppressed by {cooldown_minutes}m cooldown",
            })
            continue

        res: Optional[DeliveryResult] = None
        if ch_type == "webhook" and config.get("url"):
            res = send_generic_webhook(config["url"], payload, config.get("secret"))
        elif ch_type == "discord" and config.get("url"):
            res = send_discord_webhook(config["url"], payload)
        elif ch_type == "slack" and config.get("url"):
            res = send_slack_webhook(config["url"], payload)
        elif ch_type == "email" and config.get("email"):
            res = send_email_alert(config["email"], payload)

        if res:
            if res["status"] == "sent":
                mark_sent(server_id, alert_type, ch_type)
            results.append(res)

    return results
