"""Tests for Phase 3 Notification Pipeline & Cooldowns."""

import datetime
from unittest.mock import MagicMock, patch
from notifications import (
    NotificationPayload,
    dispatch_alert_notifications,
    is_in_cooldown,
    mark_sent,
    send_discord_webhook,
    send_generic_webhook,
    send_slack_webhook,
)


def test_cooldown_tracking():
    server_id = "srv-cool-1"
    alert_type = "HIGH_CPU"
    channel_type = "webhook"

    assert not is_in_cooldown(server_id, alert_type, channel_type, 15)
    mark_sent(server_id, alert_type, channel_type)
    assert is_in_cooldown(server_id, alert_type, channel_type, 15)


def test_send_generic_webhook_success():
    payload: NotificationPayload = {
        "title": "High CPU",
        "message": "CPU is 95%",
        "severity": "critical",
        "server_id": "srv-1",
        "server_name": "api-01",
        "alert_type": "HIGH_CPU",
        "timestamp": "2026-09-05T12:00:00Z",
        "meta": {"cpu": 95.0},
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        res = send_generic_webhook("https://webhook.site/test", payload, secret="test-secret")
        assert res["status"] == "sent"
        assert res["channel_type"] == "webhook"
        assert mock_post.called


def test_send_discord_webhook_formatting():
    payload: NotificationPayload = {
        "title": "Network Spike",
        "message": "Spike detected",
        "severity": "warning",
        "server_id": "srv-disc",
        "server_name": "web-01",
        "alert_type": "NETWORK_SPIKE",
        "timestamp": "2026-09-05T12:00:00Z",
        "meta": {},
    }

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        res = send_discord_webhook("https://discord.com/api/webhooks/test", payload)
        assert res["status"] == "sent"
        assert res["channel_type"] == "discord"
        # Check payload embed structure
        kwargs = mock_post.call_args[1]
        body = kwargs["json"]
        assert "embeds" in body
        assert body["embeds"][0]["title"] == "🚨 [WARNING] Network Spike"


def test_dispatch_alert_notifications_skips_in_cooldown():
    payload: NotificationPayload = {
        "title": "CPU Alert",
        "message": "High CPU",
        "severity": "critical",
        "server_id": "srv-skip",
        "server_name": "node-01",
        "alert_type": "HIGH_CPU",
        "timestamp": "2026-09-05T12:00:00Z",
        "meta": {},
    }
    channels = [{"id": "ch-1", "channel_type": "webhook", "config": {"url": "http://example.com"}}]

    # First dispatch marks it sent
    mark_sent("srv-skip", "HIGH_CPU", "webhook")

    results = dispatch_alert_notifications(payload, channels, cooldown_minutes=30)
    assert len(results) == 1
    assert results[0]["status"] == "cooldown_skipped"
