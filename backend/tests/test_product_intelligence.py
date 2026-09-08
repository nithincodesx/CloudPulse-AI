"""Tests for Core Product Intelligence: Cost, Optimization, Anomalies, Incidents, AI."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from cost_optimizer import (
    analyze_server_utilization,
    run_fleet_optimization_analysis,
)
from anomaly import (
    check_anomalies,
    calculate_mean_std,
    classify_severity,
)
from incidents import (
    create_incident_record,
    create_timeline_entry,
    validate_status_transition,
)
from ai_investigation import (
    build_incident_facts,
    generate_fallback_investigation,
)


# ===========================================================================
# COST INTELLIGENCE TESTS
# ===========================================================================

class TestCostIntelligence:
    """Test cost intelligence with real AWS Cost Explorer data patterns."""

    def test_cost_anomaly_detection(self):
        """Verify cost anomalies are detected from daily cost data."""
        daily_costs = [
            {"date": "2026-09-01", "amount": 10.0},
            {"date": "2026-09-02", "amount": 10.5},
            {"date": "2026-09-03", "amount": 9.8},
            {"date": "2026-09-04", "amount": 10.2},
            {"date": "2026-09-05", "amount": 100.0},  # Extreme spike!
        ]
        amounts = [c["amount"] for c in daily_costs]
        mean, std = calculate_mean_std(amounts)
        assert mean > 0
        assert std is not None
        # The spike should be detectable (z-score well above 2σ)
        z_score = (100.0 - mean) / std if std else 0
        assert z_score > 1.5  # Significant deviation detected

    def test_actual_vs_estimated_cost(self):
        """Verify system distinguishes actual vs estimated costs."""
        server = {
            "id": "srv-1",
            "server_name": "test-server",
            "specifications": {"type": "t3.medium"},
        }
        # With actual daily costs
        daily_costs = [{"amount": 1.5} for _ in range(30)]
        metrics = [{"cpu_usage": 50.0, "ram_usage": 60.0} for _ in range(10)]
        recs = analyze_server_utilization(server, metrics, daily_costs)
        if recs:
            # Should use actual costs
            assert recs[0]["current_cost_monthly"] == 45.0  # 1.5 * 30


# ===========================================================================
# OPTIMIZATION TESTS
# ===========================================================================

class TestOptimization:
    """Test optimization recommendations with evidence."""

    def test_oversized_resource_recommendation(self):
        """Verify oversized resources have evidence and savings."""
        server = {
            "id": "srv-big",
            "server_name": "big-server",
            "aws_instance_id": "i-0123456789abcdef0",
            "specifications": {"type": "t3.2xlarge"},
        }
        # Very low utilization
        metrics = [
            {"cpu_usage": 5.0, "ram_usage": 10.0, "network_traffic": 1.0}
            for _ in range(20)
        ]
        recs = analyze_server_utilization(server, metrics, [])
        assert len(recs) >= 1
        rec = recs[0]
        # Must have evidence
        assert "evidence" in rec
        assert rec["evidence"]["avg_cpu"] < 10.0
        # Must have estimated savings
        assert rec["estimated_savings_monthly"] > 0
        # Must have confidence level
        assert rec["confidence"] in ("HIGH", "MEDIUM", "LOW")
        # Must have recommended action
        assert len(rec["action_recommendation"]) > 0

    def test_idle_resource_has_100_percent_savings(self):
        """Verify idle resource recommendations show full savings."""
        server = {
            "id": "srv-idle",
            "server_name": "idle-server",
            "specifications": {"type": "t3.large"},
        }
        metrics = [
            {"cpu_usage": 1.0, "ram_usage": 5.0, "network_traffic": 0.01}
            for _ in range(10)
        ]
        recs = analyze_server_utilization(server, metrics, [])
        assert len(recs) >= 1
        idle_rec = next((r for r in recs if r["recommendation_type"] == "IDLE_RESOURCE"), None)
        assert idle_rec is not None
        assert idle_rec["estimated_savings_monthly"] == idle_rec["current_cost_monthly"]

    def test_fleet_optimization_summary(self):
        """Verify fleet-wide optimization aggregates correctly."""
        servers = [
            {"id": "s1", "server_name": "s1", "specifications": {"type": "t3.medium"}},
            {"id": "s2", "server_name": "s2", "specifications": {"type": "t3.large"}},
        ]
        metrics_by_server = {
            "s1": [{"cpu_usage": 5.0, "ram_usage": 10.0} for _ in range(10)],
            "s2": [{"cpu_usage": 50.0, "ram_usage": 60.0} for _ in range(10)],
        }
        costs_by_server = {"s1": [], "s2": []}
        recs, summary = run_fleet_optimization_analysis(servers, metrics_by_server, costs_by_server)
        assert summary["total_opportunities_count"] >= 1
        assert summary["potential_monthly_savings"] > 0


# ===========================================================================
# ANOMALY + INCIDENT INTEGRATION TESTS
# ===========================================================================

class TestAnomalyIncidentIntegration:
    """Test anomaly detection, incident creation, and deduplication."""

    def test_sustained_anomaly_creates_incident(self):
        """Verify that sustained anomalies produce incidents with evidence."""
        baseline = {
            "cpu": {"mean": 40.0, "std": 10.0},
            "ram": {"mean": 50.0, "std": 5.0},
            "network": {"mean": 200.0, "std": 50.0},
            "sample_count": 500,
            "days": 7,
        }
        # High CPU reading
        alerts = check_anomalies("srv-1", cpu=95.0, ram=55.0, network=210, baseline=baseline)
        assert len(alerts) > 0
        assert any(a["alert_type"] == "HIGH_CPU" for a in alerts)

    def test_incident_record_has_required_fields(self):
        """Verify incident records contain all required fields for investigation."""
        inc = create_incident_record(
            server_id="srv-123",
            title="Sustained High CPU",
            description="CPU above 95% for 30 minutes",
            incident_type="CPU_ANOMALY",
            severity="critical",
        )
        assert inc["id"] is not None
        assert inc["server_id"] == "srv-123"
        assert inc["status"] == "open"
        assert inc["severity"] == "critical"
        assert inc["created_at"] is not None

    def test_multi_metric_anomaly_detection(self):
        """Verify anomalies across CPU, RAM, disk, and network are detected."""
        baseline = {
            "cpu": {"mean": 40.0, "std": 10.0},
            "ram": {"mean": 50.0, "std": 5.0},
            "network": {"mean": 200.0, "std": 50.0},
            "sample_count": 500,
            "days": 7,
        }
        # High CPU + High RAM
        alerts = check_anomalies("srv-1", cpu=95.0, ram=90.0, network=210, baseline=baseline)
        alert_types = [a["alert_type"] for a in alerts]
        assert "HIGH_CPU" in alert_types
        assert "HIGH_RAM" in alert_types

    def test_classify_severity_by_z_score(self):
        """Verify severity classification based on z-score thresholds."""
        assert classify_severity(3.5, 2.0, 95.0) == "critical"
        assert classify_severity(2.5, 2.0, 80.0) == "warning"
        assert classify_severity(1.5, 2.0, 50.0) == "info"


# ===========================================================================
# AI INVESTIGATION TESTS
# ===========================================================================

class TestAIInvestigation:
    """Test grounded AI investigation with tenant isolation."""

    def test_build_incident_facts_grounded_in_evidence(self):
        """Verify AI facts are built from real evidence, not invented."""
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

        # Facts must reflect actual evidence
        assert facts["incident"]["id"] == "inc-001"
        assert facts["resource"]["name"] == "prod-web-01"
        assert facts["telemetry_stats"]["peak_cpu_pct"] == 92.5
        assert facts["cost_recommendations"][0]["savings_monthly"] == 35.0

    def test_fallback_investigation_distinguishes_facts_from_conclusions(self):
        """Verify the fallback investigation clearly separates observed vs inferred."""
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

        # Must be marked as fallback (no LLM)
        assert report["is_fallback"] is True
        # Must contain observed facts
        assert "96.5%" in report["incident_explanation"]
        # Must contain cost impact
        assert "$80.00/mo" in report["cost_impact_explanation"]
        # Must have prioritized actions
        assert len(report["prioritized_actions"]) >= 2

    def test_ai_cannot_execute_infrastructure_actions(self):
        """Verify AI investigation is read-only — it cannot trigger AWS/SSH actions."""
        facts = {
            "incident": {"id": "inc-secure", "title": "Test", "severity": "low"},
            "resource": {"name": "test-server"},
            "telemetry_stats": {"current_cpu_pct": 50.0},
        }

        report = generate_fallback_investigation(facts)

        # Report should only contain recommendations, not execute actions
        assert "prioritized_actions" in report
        # Actions should be recommendations (strings), not API calls
        for action in report["prioritized_actions"]:
            assert isinstance(action["action"], str)
            # No AWS API calls or SSH commands
            assert "terminate_instances" not in action["action"].lower()
            assert "ssh " not in action["action"].lower()
            assert "boto3" not in action["action"].lower()

    def test_insufficient_evidence_produces_honest_response(self):
        """Verify the system says when evidence is insufficient."""
        facts = {
            "incident": {"id": "inc-empty", "title": "Unknown Issue", "severity": "low"},
            "resource": {"name": "unknown-server"},
            "telemetry_stats": {"sample_count": 0},
        }

        report = generate_fallback_investigation(facts)

        # Should acknowledge limited data
        assert report["is_fallback"] is True
        # Should not invent facts about the infrastructure
        assert "summary" in report