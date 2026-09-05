"""Tests for Phase 3 Alert Rule Engine."""

import pytest
from alert_rules import evaluate_metric_against_rules, evaluate_optimization_rules


def test_cpu_rule_triggers_on_threshold():
    rules = [
        {
            "id": "rule-cpu-1",
            "name": "High CPU Alert",
            "rule_type": "CPU_ANOMALY",
            "condition_config": {"threshold": 80.0},
            "severity": "critical",
            "cooldown_minutes": 10,
            "channels": ["webhook", "discord"],
            "enabled": True,
        }
    ]
    server = {"id": "srv-123", "server_name": "prod-api-01"}
    metric = {"cpu_usage": 88.5, "ram_usage": 40.0, "network_traffic": 10.0}

    triggered = evaluate_metric_against_rules(rules, server, metric)
    assert len(triggered) == 1
    t = triggered[0]
    assert t["rule_id"] == "rule-cpu-1"
    assert t["severity"] == "critical"
    assert "88.5%" in t["notification_payload"]["message"]
    assert t["target_channels"] == ["webhook", "discord"]


def test_disabled_rule_does_not_trigger():
    rules = [
        {
            "id": "rule-ram-1",
            "name": "RAM Rule",
            "rule_type": "RAM_ANOMALY",
            "condition_config": {"threshold": 75.0},
            "severity": "warning",
            "enabled": False,
        }
    ]
    server = {"id": "srv-123", "server_name": "prod-api-01"}
    metric = {"cpu_usage": 10.0, "ram_usage": 95.0, "network_traffic": 5.0}

    triggered = evaluate_metric_against_rules(rules, server, metric)
    assert len(triggered) == 0


def test_network_anomaly_rule_triggers():
    rules = [
        {
            "id": "rule-net-1",
            "name": "Network Spike",
            "rule_type": "NETWORK_ANOMALY",
            "condition_config": {"threshold": 250.0},
            "severity": "warning",
            "enabled": True,
        }
    ]
    server = {"id": "srv-net", "server_name": "db-primary"}
    metric = {"cpu_usage": 20.0, "ram_usage": 50.0, "network_traffic": 320.0}

    triggered = evaluate_metric_against_rules(rules, server, metric)
    assert len(triggered) == 1
    assert "320.0 MB" in triggered[0]["notification_payload"]["message"]


def test_idle_resource_rule_triggers_from_anomaly():
    rules = [
        {
            "id": "rule-idle",
            "name": "Idle Warning",
            "rule_type": "IDLE_RESOURCE",
            "severity": "info",
            "enabled": True,
        }
    ]
    server = {"id": "srv-idle", "server_name": "dev-box"}
    metric = {"cpu_usage": 1.2, "ram_usage": 8.0, "network_traffic": 0.1}
    anomalies = [{"alert_type": "IDLE_RESOURCE", "message": "Resource idle"}]

    triggered = evaluate_metric_against_rules(rules, server, metric, anomalies)
    assert len(triggered) == 1
    assert triggered[0]["rule_type"] == "IDLE_RESOURCE"


def test_savings_threshold_rule():
    rules = [
        {
            "id": "rule-savings",
            "name": "Big Savings Alert",
            "rule_type": "SAVINGS_THRESHOLD",
            "condition_config": {"savings_min": 75.0},
            "severity": "info",
            "enabled": True,
        }
    ]
    recs = [
        {
            "server_id": "srv-1",
            "resource_name": "node-1",
            "estimated_savings_monthly": 50.0,
            "action_recommendation": "Downsize",
        },
        {
            "server_id": "srv-2",
            "resource_name": "node-2",
            "estimated_savings_monthly": 45.0,
            "action_recommendation": "Stop idle node",
        },
    ]

    triggered = evaluate_optimization_rules(rules, recs)
    assert len(triggered) == 1
    assert "$95.00/mo" in triggered[0]["notification_payload"]["message"]
