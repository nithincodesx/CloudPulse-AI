"""Tests for Phase 3 Incident Lifecycle & State Machine."""

import pytest
from incidents import (
    create_incident_record,
    create_timeline_entry,
    validate_status_transition,
)


def test_create_incident_record():
    inc = create_incident_record(
        server_id="srv-123",
        title="High Memory Saturation",
        description="RAM reached 94%",
        incident_type="RAM_ANOMALY",
        severity="critical",
    )
    assert inc["server_id"] == "srv-123"
    assert inc["title"] == "High Memory Saturation"
    assert inc["status"] == "open"
    assert inc["severity"] == "critical"
    assert inc["id"] is not None


def test_create_timeline_entry():
    t = create_timeline_entry(
        incident_id="inc-999",
        event_type="DETECTION",
        message="Alert rule High CPU triggered.",
        actor="AlertEngine",
        meta={"cpu": 95.0},
    )
    assert t["incident_id"] == "inc-999"
    assert t["event_type"] == "DETECTION"
    assert t["actor"] == "AlertEngine"
    assert t["meta"]["cpu"] == 95.0


def test_validate_status_transition():
    # Valid transitions
    assert validate_status_transition("open", "acknowledged")
    assert validate_status_transition("open", "resolved")
    assert validate_status_transition("acknowledged", "resolved")
    assert validate_status_transition("resolved", "open")  # Reopen

    # Invalid transitions
    assert not validate_status_transition("resolved", "unknown_status")
    assert not validate_status_transition("non_existent", "open")
