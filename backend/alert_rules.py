"""CloudPulse AI — Alert Rule Engine.

Evaluates incoming telemetry metrics, statistical anomaly events, and cost optimization
recommendations against customizable user-defined alert rules.

SUPPORTED RULE TYPES:
1. CPU_ANOMALY: High CPU usage percentage or standard deviation threshold.
2. RAM_ANOMALY: High RAM usage percentage threshold.
3. NETWORK_ANOMALY: Network bandwidth spike threshold.
4. IDLE_RESOURCE: Resource chronically idle across CPU/RAM dimensions.
5. BUDGET_SPIKE: Daily cloud spend spike ratio.
6. SAVINGS_THRESHOLD: Potential monthly savings exceeds dollar amount (e.g. > $50/mo).
7. CUSTOM: Combined threshold conditions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from notifications import NotificationPayload


class TriggeredRule(TypedDict):
    rule_id: str
    rule_name: str
    rule_type: str
    severity: str
    cooldown_minutes: int
    target_channels: list[str]
    notification_payload: NotificationPayload


def evaluate_metric_against_rules(
    rules: list[dict],
    server: dict,
    metric_payload: dict,
    anomaly_events: Optional[list[dict]] = None,
) -> list[TriggeredRule]:
    """Evaluate one server's latest metric and anomaly events against active alert rules."""
    triggered: list[TriggeredRule] = []
    server_id = str(server.get("id", ""))
    server_name = server.get("server_name") or server_id
    anomalies = anomaly_events or []

    cpu = float(metric_payload.get("cpu_usage", 0.0))
    ram = float(metric_payload.get("ram_usage", 0.0))
    net = float(metric_payload.get("network_traffic", 0.0))
    now_iso = datetime.now(timezone.utc).isoformat()

    for rule in rules:
        if not rule.get("enabled", True):
            continue

        rule_type = rule.get("rule_type", "").upper()
        config = rule.get("condition_config", {})
        severity = rule.get("severity", "warning").lower()
        cooldown = int(rule.get("cooldown_minutes", 15))
        channels = rule.get("channels", ["webhook"])

        is_match = False
        message = ""

        if rule_type == "CPU_ANOMALY":
            thresh = float(config.get("threshold", 85.0))
            if cpu >= thresh:
                is_match = True
                message = f"CPU usage on {server_name} reached {cpu:.1f}% (threshold: {thresh:.1f}%)."
            elif any(a.get("alert_type") == "HIGH_CPU" for a in anomalies):
                is_match = True
                message = f"Statistical CPU anomaly detected on {server_name} (current: {cpu:.1f}%)."

        elif rule_type == "RAM_ANOMALY":
            thresh = float(config.get("threshold", 90.0))
            if ram >= thresh:
                is_match = True
                message = f"RAM usage on {server_name} reached {ram:.1f}% (threshold: {thresh:.1f}%)."

        elif rule_type == "NETWORK_ANOMALY":
            thresh = float(config.get("threshold", 500.0))
            if net >= thresh or any(a.get("alert_type") == "NETWORK_ANOMALY" for a in anomalies):
                is_match = True
                message = f"Network spike of {net:.1f} MB observed on {server_name}."

        elif rule_type == "IDLE_RESOURCE":
            if any(a.get("alert_type") == "IDLE_RESOURCE" for a in anomalies):
                is_match = True
                message = f"Resource {server_name} is chronically idle (CPU {cpu:.1f}%, RAM {ram:.1f}%)."

        elif rule_type == "BUDGET_SPIKE":
            if any(a.get("alert_type") == "BUDGET_SPIKE" for a in anomalies):
                is_match = True
                message = f"Cloud spend surge detected for {server_name} exceeding 2x baseline."

        if is_match:
            payload: NotificationPayload = {
                "title": f"{rule.get('name', rule_type)} Triggered",
                "message": message,
                "severity": severity,
                "server_id": server_id,
                "server_name": server_name,
                "alert_type": rule_type,
                "timestamp": now_iso,
                "meta": {"rule_id": rule.get("id"), "cpu": cpu, "ram": ram, "network": net},
            }
            triggered.append({
                "rule_id": str(rule.get("id", "")),
                "rule_name": str(rule.get("name", rule_type)),
                "rule_type": rule_type,
                "severity": severity,
                "cooldown_minutes": cooldown,
                "target_channels": channels if isinstance(channels, list) else ["webhook"],
                "notification_payload": payload,
            })

    return triggered


def evaluate_optimization_rules(
    rules: list[dict],
    recommendations: list[dict],
) -> list[TriggeredRule]:
    """Evaluate fleet-wide cost recommendations against SAVINGS_THRESHOLD rules."""
    triggered: list[TriggeredRule] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if rule.get("rule_type") != "SAVINGS_THRESHOLD":
            continue

        config = rule.get("condition_config", {})
        min_savings = float(config.get("savings_min", 50.0))
        severity = rule.get("severity", "info").lower()
        cooldown = int(rule.get("cooldown_minutes", 60))
        channels = rule.get("channels", ["webhook"])

        total_savings = sum(float(r.get("estimated_savings_monthly", 0.0)) for r in recommendations)
        if total_savings >= min_savings:
            high_rec = max(recommendations, key=lambda r: float(r.get("estimated_savings_monthly", 0.0)), default=None)
            res_name = high_rec.get("resource_name", "fleet") if high_rec else "fleet"

            payload: NotificationPayload = {
                "title": f"Cost Optimization Opportunity (> ${min_savings:.0f}/mo)",
                "message": (
                    f"Identified ${total_savings:.2f}/mo potential savings across {len(recommendations)} resources. "
                    f"Top opportunity: {high_rec.get('action_recommendation', 'downsize underutilized nodes') if high_rec else 'optimize resources'}."
                ),
                "severity": severity,
                "server_id": high_rec.get("server_id", "fleet") if high_rec else "fleet",
                "server_name": res_name,
                "alert_type": "SAVINGS_THRESHOLD",
                "timestamp": now_iso,
                "meta": {"total_savings": total_savings, "min_savings": min_savings},
            }
            triggered.append({
                "rule_id": str(rule.get("id", "")),
                "rule_name": str(rule.get("name", "Savings Threshold")),
                "rule_type": "SAVINGS_THRESHOLD",
                "severity": severity,
                "cooldown_minutes": cooldown,
                "target_channels": channels if isinstance(channels, list) else ["webhook"],
                "notification_payload": payload,
            })

    return triggered
