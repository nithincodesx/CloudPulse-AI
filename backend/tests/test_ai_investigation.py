"""Tests for Phase 3 Grounded AI Investigation Engine."""

import pytest
from ai_investigation import (
    build_incident_facts,
    generate_fallback_investigation,
    run_ai_incident_investigation,
)


def test_build_incident_facts_structure():
    incident = {
        "id": "inc-001",
        "title": "CPU Spike",
        "incident_type": "CPU_ANOMALY",
        "severity": "critical",
        "status": "open",
        "created_at": "2026-09-05T10:00:00Z",
    }
    server = {
        "id": "srv-001",
        "server_name": "prod-web-01",
        "aws_instance_id": "i-abcdef123",
        "aws_region": "us-east-1",
        "specifications": {"type": "t3.large", "vcpus": 2, "ram_gb": 8},
    }
    metrics = [
        {"cpu_usage": 40.0, "ram_usage": 50.0, "network_traffic": 10.0},
        {"cpu_usage": 92.5, "ram_usage": 55.0, "network_traffic": 12.0},
    ]
    recs = [
        {
            "recommendation_type": "RIGHT_SIZING",
            "estimated_savings_monthly": 35.0,
            "action_recommendation": "Downsize to t3.medium",
            "confidence": "HIGH",
        }
    ]

    facts = build_incident_facts(incident, server, metrics, None, recs)

    assert facts["incident"]["id"] == "inc-001"
    assert facts["resource"]["name"] == "prod-web-01"
    assert facts["resource"]["aws_instance_id"] == "i-abcdef123"
    assert facts["telemetry_stats"]["peak_cpu_pct"] == 92.5
    assert facts["telemetry_stats"]["current_cpu_pct"] == 92.5
    assert len(facts["cost_recommendations"]) == 1
    assert facts["cost_recommendations"][0]["savings_monthly"] == 35.0


def test_generate_fallback_investigation_is_deterministic():
    facts = {
        "incident": {
            "id": "inc-100",
            "title": "RAM Exhaustion",
            "severity": "critical",
            "type": "RAM_ANOMALY",
        },
        "resource": {
            "name": "cache-cluster-01",
            "instance_type": "r5.large",
        },
        "telemetry_stats": {
            "current_cpu_pct": 20.0,
            "current_ram_pct": 96.5,
            "sample_count": 25,
        },
        "cost_recommendations": [
            {
                "type": "IDLE_RESOURCE",
                "savings_monthly": 80.0,
                "action": "Terminate unused worker",
                "confidence": "HIGH",
            }
        ],
    }

    report = generate_fallback_investigation(facts)
    assert report["is_fallback"] is True
    assert "Critical severity incident on cache-cluster-01" in report["summary"]
    assert "96.5%" in report["incident_explanation"]
    assert "$80.00/mo" in report["cost_impact_explanation"]
    assert len(report["prioritized_actions"]) == 2
    assert report["prioritized_actions"][0]["priority"] == "High"
    assert report["prioritized_actions"][1]["priority"] == "Critical"
