"""CloudPulse AI — Incident Lifecycle & State Machine.

Manages the lifecycle of operational infrastructure incidents:
Detection → Alert → Acknowledgement → Investigation → Resolution

STATUSES:
- OPEN: Active incident requiring operator review.
- ACKNOWLEDGED: Operator has acknowledged and triaged the incident.
- RESOLVED: Root cause addressed and telemetry restored to normal.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from logging_conf import get_logger

logger = get_logger("backend.incidents")


class TimelineEvent(TypedDict):
    event_type: str  # DETECTION, NOTIFICATION_SENT, ACKNOWLEDGED, AI_INVESTIGATION, NOTE_ADDED, RESOLVED
    actor: str
    message: str
    meta: dict[str, Any]
    created_at: str


def create_incident_record(
    server_id: str,
    title: str,
    description: str,
    incident_type: str,
    severity: str = "warning",
    root_cause_summary: Optional[str] = None,
) -> dict[str, Any]:
    """Construct a new incident dictionary ready for database insertion."""
    now_iso = datetime.now(timezone.utc).isoformat()
    inc_id = str(uuid.uuid4())
    return {
        "id": inc_id,
        "server_id": server_id,
        "title": title,
        "description": description,
        "incident_type": incident_type,
        "severity": severity,
        "status": "open",
        "root_cause_summary": root_cause_summary,
        "ai_investigation": {},
        "created_at": now_iso,
        "updated_at": now_iso,
    }


def create_timeline_entry(
    incident_id: str,
    event_type: str,
    message: str,
    actor: str = "system",
    meta: Optional[dict] = None,
) -> dict[str, Any]:
    """Construct an incident timeline event."""
    return {
        "id": str(uuid.uuid4()),
        "incident_id": incident_id,
        "event_type": event_type,
        "actor": actor,
        "message": message,
        "meta": meta or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def validate_status_transition(current_status: str, new_status: str) -> bool:
    """Validate allowable state transitions in the incident lifecycle."""
    allowed = {
        "open": ["open", "acknowledged", "resolved"],
        "acknowledged": ["acknowledged", "resolved", "open"],
        "resolved": ["resolved", "open"],  # Reopen if needed
    }
    return new_status in allowed.get(current_status, [])
