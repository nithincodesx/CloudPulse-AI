"""Billing & SaaS usage metrics calculation service for CloudPulse-AI.

Aggregates resource consumption, telemetry volume, active nodes, and connected
accounts for an organization to enable subscription readiness.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from database import (
    get_organization_by_id,
    list_aws_connections_for_org,
    list_servers_for_org,
    get_telemetry_metrics_count,
    list_alerts,
)

logger = logging.getLogger("cloudpulse.billing")


def calculate_organization_usage(organization_id: str | UUID) -> dict[str, Any]:
    """Computes comprehensive usage statistics for an organization."""
    org_id_str = str(organization_id)
    org = get_organization_by_id(org_id_str)
    if not org:
        raise ValueError(f"Organization {org_id_str} not found")

    connections = list_aws_connections_for_org(org_id_str)
    servers = list_servers_for_org(org_id_str)
    alerts = list_alerts(unresolved_only=True)
    org_alerts = [a for a in alerts if a.get("organization_id") == org_id_str or not a.get("organization_id")]

    # Telemetry volume in last 24h and last 30d
    count_24h = get_telemetry_metrics_count(org_id_str, hours=24)
    count_30d = get_telemetry_metrics_count(org_id_str, hours=24 * 30)

    return {
        "organization_id": org_id_str,
        "plan_tier": org.get("plan_tier", "free"),
        "connected_aws_accounts": len(connections),
        "max_aws_connections": org.get("max_aws_connections", 5),
        "monitored_nodes": len(servers),
        "active_alerts": len(org_alerts),
        "retention_days": org.get("retention_days", 30),
        "telemetry_metrics_24h": count_24h,
        "telemetry_metrics_30d": count_30d,
    }
