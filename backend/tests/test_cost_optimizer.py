"""Deterministic unit tests for the Rule-Based Cost Optimization Engine (Phase 2).

Tests:
- AWS verified pricing lookup and honest unpriced fallback
- Right-sizing candidate calculation
- Idle resource detection & avoidable spend calculation
- Low utilization & downsize recommendations
- Cost spike detection
- Fleet-wide optimization summary aggregation
"""

from pricing import get_instance_pricing, find_downsize_target
from cost_optimizer import (
    analyze_server_utilization,
    run_fleet_optimization_analysis,
)


def test_pricing_lookup_known_instance():
    p = get_instance_pricing("t3.large")
    assert p is not None
    assert p["vcpus"] == 2
    assert p["memory_gb"] == 8.0
    assert p["hourly_rate"] == 0.0832
    assert p["monthly_cost"] == round(0.0832 * 730, 2)
    assert p["is_known"] is True


def test_pricing_lookup_unknown_instance_returns_none():
    assert get_instance_pricing("custom.instance.type") is None
    assert get_instance_pricing(None) is None


def test_find_downsize_target():
    # t3.large with very low peak CPU 15% and avg CPU 5% should downsize safely to t3.small or t3.micro
    target = find_downsize_target("t3.large", peak_cpu=14.0, avg_cpu=4.0)
    assert target is not None
    target_type, target_pricing = target
    assert target_type in ("t3.small", "t3.micro", "t3.nano")
    assert target_pricing["monthly_cost"] < 60.74  # Cheaper than t3.large


def test_find_downsize_target_already_smallest():
    assert find_downsize_target("t3.nano", peak_cpu=10.0, avg_cpu=2.0) is None


def test_idle_resource_analyzer():
    server = {
        "id": "srv-idle-1",
        "server_name": "dev-idle-host",
        "aws_instance_id": "i-0123456789abcdef0",
        "aws_region": "us-east-1",
        "specifications": {"type": "t3.medium"},
    }
    # Synthetic metrics with 2% avg CPU and 8% RAM
    metrics = [
        {"cpu_usage": 2.0, "ram_usage": 8.0, "network_traffic": 0.1}
        for _ in range(10)
    ]
    recs = analyze_server_utilization(server, metrics_history=metrics, daily_costs=[])
    assert len(recs) == 1
    rec = recs[0]
    assert rec["recommendation_type"] == "IDLE_RESOURCE"
    assert rec["confidence"] == "HIGH"
    assert rec["current_cost_monthly"] == 30.37  # t3.medium monthly rate
    assert rec["estimated_savings_monthly"] == 30.37  # 100% savings from stopping idle node
    assert "chronically idle" in rec["problem_summary"]


def test_right_sizing_analyzer():
    server = {
        "id": "srv-overprov-1",
        "server_name": "api-worker-1",
        "aws_instance_id": "i-9876543210fedcba0",
        "aws_region": "us-east-1",
        "specifications": {"type": "t3.large"},
    }
    # Synthetic metrics: average CPU 12%, peak CPU 28%
    metrics = [
        {"cpu_usage": 10.0 + (i % 5), "ram_usage": 25.0, "network_traffic": 20.0}
        for i in range(10)
    ]
    recs = analyze_server_utilization(server, metrics_history=metrics, daily_costs=[])
    assert len(recs) == 1
    rec = recs[0]
    assert rec["recommendation_type"] == "RIGHT_SIZING"
    assert rec["target_resource_type"] is not None
    assert rec["estimated_savings_monthly"] > 0
    assert rec["pricing_source"] == "aws_catalog"
    assert "Downsize instance" in rec["action_recommendation"]


def test_cost_spike_analyzer():
    server = {
        "id": "srv-spike-1",
        "server_name": "batch-processor",
        "specifications": {"type": "t3.small"},
    }
    metrics = [{"cpu_usage": 45.0, "ram_usage": 50.0} for _ in range(5)]
    # Daily costs: baseline ~$1.00/day, sudden spike to $8.50/day
    daily_costs = [
        {"cost_date": "2026-09-01", "amount": 1.05},
        {"cost_date": "2026-09-02", "amount": 0.98},
        {"cost_date": "2026-09-03", "amount": 1.10},
        {"cost_date": "2026-09-04", "amount": 1.02},
        {"cost_date": "2026-09-05", "amount": 8.50},  # >2x spike
    ]
    recs = analyze_server_utilization(server, metrics_history=metrics, daily_costs=daily_costs)
    assert any(r["recommendation_type"] == "COST_SPIKE" for r in recs)
    spike_rec = next(r for r in recs if r["recommendation_type"] == "COST_SPIKE")
    assert spike_rec["confidence"] == "HIGH"
    assert "spiked to $8.50/day" in spike_rec["problem_summary"]


def test_run_fleet_optimization_analysis():
    servers = [
        {
            "id": "s1",
            "server_name": "idle-node",
            "specifications": {"type": "t3.medium"},
        },
        {
            "id": "s2",
            "server_name": "normal-node",
            "specifications": {"type": "t3.small"},
        },
    ]
    metrics_by_server = {
        "s1": [{"cpu_usage": 1.5, "ram_usage": 5.0} for _ in range(10)],
        "s2": [{"cpu_usage": 65.0, "ram_usage": 70.0} for _ in range(10)],
    }
    costs_by_server = {"s1": [], "s2": []}

    recs, summary = run_fleet_optimization_analysis(servers, metrics_by_server, costs_by_server)
    assert len(recs) >= 1
    assert summary["total_monthly_spend"] > 0
    assert summary["potential_monthly_savings"] > 0
    assert summary["total_opportunities_count"] >= 1
    assert len(summary["highest_cost_resources"]) == 2
