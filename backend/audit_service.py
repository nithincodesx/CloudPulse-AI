"""Audit logging service for CloudPulse-AI.

Records high-integrity, security-relevant events across organizations
without logging secrets or sensitive credentials.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from database import (
    create_audit_log_entry,
    list_audit_log_entries,
)

logger = logging.getLogger("cloudpulse.audit")


# Predefined audit event action constants
class AuditActions:
    AWS_CONNECTED = "AWS_CONNECTED"
    AWS_DISCONNECTED = "AWS_DISCONNECTED"
    AWS_VERIFIED = "AWS_VERIFIED"
    AWS_HEALTH_CHECK = "AWS_HEALTH_CHECK"
    RESOURCE_DISCOVERED = "RESOURCE_DISCOVERED"
    ALERT_TRIGGERED = "ALERT_TRIGGERED"
    ALERT_RESOLVED = "ALERT_RESOLVED"
    INCIDENT_CREATED = "INCIDENT_CREATED"
    INCIDENT_STATUS_CHANGED = "INCIDENT_STATUS_CHANGED"
    SETTINGS_UPDATED = "SETTINGS_UPDATED"
    MEMBER_INVITED = "MEMBER_INVITED"
    MEMBER_ROLE_UPDATED = "MEMBER_ROLE_UPDATED"
    MEMBER_REMOVED = "MEMBER_REMOVED"
    SYNC_COMPLETED = "SYNC_COMPLETED"
    SYNC_FAILED = "SYNC_FAILED"


def sanitize_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Strip any accidental credential fields before persisting audit records."""
    if not meta:
        return {}
    sanitized = {}
    forbidden_substrings = ("secret", "token", "password", "key", "access_key", "credential", "session")
    for k, v in meta.items():
        if any(bad in k.lower() for bad in forbidden_substrings):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_metadata(v)
        else:
            sanitized[k] = v
    return sanitized


def log_audit_event(
    organization_id: str | UUID,
    action: str,
    resource_type: str,
    actor_id: str | UUID | None = None,
    actor_email: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict | None:
    """Safely records an audit log event in the database."""
    safe_metadata = sanitize_metadata(metadata)
    try:
        entry = {
            "organization_id": str(organization_id),
            "actor_id": str(actor_id) if actor_id else None,
            "actor_email": actor_email,
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "metadata": safe_metadata,
        }
        res = create_audit_log_entry(entry)
        logger.info(
            "Audit event logged: org=%s action=%s resource_type=%s resource_id=%s actor=%s",
            organization_id,
            action,
            resource_type,
            resource_id,
            actor_email or actor_id or "system",
        )
        return res
    except Exception as exc:
        logger.error("Failed to record audit event: %s", exc)
        return None


def get_audit_trail(
    organization_id: str | UUID,
    limit: int = 50,
    offset: int = 0,
    action_filter: str | None = None,
) -> list[dict]:
    """Retrieves paginated audit events for an organization."""
    return list_audit_log_entries(
        str(organization_id),
        limit=limit,
        offset=offset,
        action_filter=action_filter,
    )
