"""CloudPulse AI — Rule-Based Cloud Cost Optimization Engine.

Evaluates infrastructure resources against AWS Cost Explorer data, discovered AWS EC2
specifications, and historical telemetry metrics. Produces transparent, evidence-based
recommendations for idle resources, underutilized nodes, right-sizing candidates, and cost spikes.

Adheres strictly to honest pricing: uses verified AWS On-Demand catalogs (pricing.py)
and clearly marks estimated or unpriced resources without fabricating figures.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from pricing import find_downsize_target, get_instance_pricing


class OptimizationEvidence(TypedDict):
    avg_cpu: float
    peak_cpu: float
    avg_ram: float
    peak_ram: float
    sample_count: int
    current_instance_type: Optional[str]
    target_instance_type: Optional[str]
    current_monthly_rate: float
    target_monthly_rate: float
    waste_reasons: list[str]


class RecommendationOut(TypedDict):
    id: Optional[str]
    server_id: str
    service_name: str
    resource_id: Optional[str]
    resource_name: str
    region: Optional[str]
    recommendation_type: str  # 'IDLE_RESOURCE', 'LOW_UTILIZATION', 'RIGHT_SIZING', 'COST_SPIKE'
    severity: str  # 'info', 'warning', 'critical'
    current_cost_monthly: float
    estimated_savings_monthly: float
    estimated_avoidable_cost: float
    confidence: str  # 'HIGH', 'MEDIUM', 'LOW'
    pricing_source: str
    problem_summary: str
    action_recommendation: str
    target_resource_type: Optional[str]
    evidence: dict[str, Any]
    status: str  # 'active', 'applied', 'dismissed'
    created_at: Optional[str]


class OptimizationSummary(TypedDict):
    total_monthly_spend: float
    estimated_avoidable_spend: float
    potential_monthly_savings: float
    total_opportunities_count: int
    highest_cost_resources: list[dict[str, Any]]
    highest_savings_opportunities: list[dict[str, Any]]
    by_type_counts: dict[str, int]
    by_severity_counts: dict[str, int]


# ---------------------------------------------------------------------------
# Core Rule-Based Resource Analyzers
# ---------------------------------------------------------------------------

def analyze_server_utilization(
    server: dict,
    metrics_history: list[dict],
    daily_costs: list[dict],
) -> list[RecommendationOut]:
    """Evaluate one server and its telemetry/cost history for cost optimization opportunities."""
    recommendations: list[RecommendationOut] = []
    server_id = str(server.get("id", ""))
    server_name = server.get("server_name") or server_id
    specs = server.get("specifications") or {}
    instance_type = specs.get("type")
    region = server.get("aws_region") or "us-east-1"
    resource_id = server.get("aws_instance_id") or server_id

    # 1. Determine baseline cost (from AWS Cost Explorer daily spend or verified pricing catalog)
    pricing_info = get_instance_pricing(instance_type)
    pricing_source = "aws_catalog" if pricing_info else "estimated"

    # Monthly cost from daily costs if available (30-day sum) or pricing catalog
    if daily_costs:
        monthly_cost = round(sum(float(c.get("amount", 0.0)) for c in daily_costs), 2)
    elif pricing_info:
        monthly_cost = pricing_info["monthly_cost"]
    else:
        monthly_cost = 0.0
        pricing_source = "unpriced"

    if not metrics_history or len(metrics_history) < 2:
        # Not enough telemetry to make confident recommendations
        return recommendations

    cpu_values = [float(m["cpu_usage"]) for m in metrics_history if m.get("cpu_usage") is not None]
    ram_values = [float(m["ram_usage"]) for m in metrics_history if m.get("ram_usage") is not None]

    if not cpu_values:
        return recommendations

    avg_cpu = round(sum(cpu_values) / len(cpu_values), 1)
    peak_cpu = round(max(cpu_values), 1)
    avg_ram = round(sum(ram_values) / len(ram_values), 1) if ram_values else 0.0
    peak_ram = round(max(ram_values), 1) if ram_values else 0.0
    sample_count = len(cpu_values)

    confidence = "HIGH" if sample_count >= 10 else ("MEDIUM" if sample_count >= 5 else "LOW")

    # -----------------------------------------------------------------------
    # Rule 1: IDLE_RESOURCE (chronically idle, e.g., avg CPU < 5%, RAM < 15%)
    # -----------------------------------------------------------------------
    if avg_cpu < 5.0 and peak_cpu < 15.0 and (not ram_values or avg_ram < 20.0):
        savings = monthly_cost if monthly_cost > 0 else 0.0
        reasons = [
            f"Average CPU utilization is only {avg_cpu}% (threshold < 5.0%)",
            f"Peak CPU observed was {peak_cpu}% (threshold < 15.0%)",
        ]
        if ram_values:
            reasons.append(f"Average RAM usage is {avg_ram}%")

        recommendations.append({
            "id": None,
            "server_id": server_id,
            "service_name": "ec2",
            "resource_id": resource_id,
            "resource_name": server_name,
            "region": region,
            "recommendation_type": "IDLE_RESOURCE",
            "severity": "critical" if monthly_cost > 50.0 else "warning",
            "current_cost_monthly": monthly_cost,
            "estimated_savings_monthly": savings,
            "estimated_avoidable_cost": savings,
            "confidence": confidence,
            "pricing_source": pricing_source,
            "problem_summary": f"Instance '{server_name}' has been chronically idle with {avg_cpu}% average CPU.",
            "action_recommendation": f"Stop or terminate instance {resource_id} to avoid unnecessary spend.",
            "target_resource_type": None,
            "evidence": {
                "avg_cpu": avg_cpu,
                "peak_cpu": peak_cpu,
                "avg_ram": avg_ram,
                "peak_ram": peak_ram,
                "sample_count": sample_count,
                "current_instance_type": instance_type,
                "waste_reasons": reasons,
            },
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return recommendations  # If completely idle, no need to also suggest right-sizing

    # -----------------------------------------------------------------------
    # Rule 2: RIGHT_SIZING & LOW_UTILIZATION (e.g., avg CPU < 20%, peak CPU < 40%)
    # -----------------------------------------------------------------------
    if avg_cpu < 20.0 and peak_cpu < 40.0 and instance_type:
        downsize = find_downsize_target(instance_type, peak_cpu=peak_cpu, avg_cpu=avg_cpu, peak_ram=peak_ram)
        if downsize:
            target_type, target_pricing = downsize
            curr_monthly = pricing_info["monthly_cost"] if pricing_info else monthly_cost
            target_monthly = target_pricing["monthly_cost"]
            monthly_savings = max(0.0, round(curr_monthly - target_monthly, 2))

            if monthly_savings > 0.5:
                reasons = [
                    f"Average CPU {avg_cpu}% and Peak CPU {peak_cpu}% do not require {instance_type}",
                    f"Target instance {target_type} ({target_pricing['vcpus']} vCPUs, {target_pricing['memory_gb']} GB RAM) provides ample headroom",
                ]
                recommendations.append({
                    "id": None,
                    "server_id": server_id,
                    "service_name": "ec2",
                    "resource_id": resource_id,
                    "resource_name": server_name,
                    "region": region,
                    "recommendation_type": "RIGHT_SIZING",
                    "severity": "warning",
                    "current_cost_monthly": curr_monthly,
                    "estimated_savings_monthly": monthly_savings,
                    "estimated_avoidable_cost": monthly_savings,
                    "confidence": confidence,
                    "pricing_source": pricing_source,
                    "problem_summary": f"Overprovisioned instance: {instance_type} is underutilized (avg CPU {avg_cpu}%, peak {peak_cpu}%).",
                    "action_recommendation": f"Downsize instance from {instance_type} to {target_type}.",
                    "target_resource_type": target_type,
                    "evidence": {
                        "avg_cpu": avg_cpu,
                        "peak_cpu": peak_cpu,
                        "avg_ram": avg_ram,
                        "peak_ram": peak_ram,
                        "sample_count": sample_count,
                        "current_instance_type": instance_type,
                        "target_instance_type": target_type,
                        "current_monthly_rate": curr_monthly,
                        "target_monthly_rate": target_monthly,
                        "waste_reasons": reasons,
                    },
                    "status": "active",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })

    # -----------------------------------------------------------------------
    # Rule 3: COST_SPIKE (Recent daily cost > 2x historical average)
    # -----------------------------------------------------------------------
    if daily_costs and len(daily_costs) >= 4:
        amounts = [float(c["amount"]) for c in daily_costs if c.get("amount") is not None]
        latest_amount = amounts[-1]
        prior_amounts = amounts[:-1]
        avg_prior = sum(prior_amounts) / len(prior_amounts)

        if avg_prior > 0.05 and latest_amount > 2.0 * avg_prior:
            spike_delta = latest_amount - avg_prior
            avoidable = round(spike_delta * 30.0, 2)
            recommendations.append({
                "id": None,
                "server_id": server_id,
                "service_name": "ec2",
                "resource_id": resource_id,
                "resource_name": server_name,
                "region": region,
                "recommendation_type": "COST_SPIKE",
                "severity": "critical" if spike_delta > 10.0 else "warning",
                "current_cost_monthly": monthly_cost,
                "estimated_savings_monthly": avoidable,
                "estimated_avoidable_cost": avoidable,
                "confidence": "HIGH",
                "pricing_source": "aws_cost_explorer",
                "problem_summary": f"Daily spend spiked to ${latest_amount:.2f}/day (historical average ${avg_prior:.2f}/day).",
                "action_recommendation": "Inspect recent traffic spikes, disk expansions, or runaway background tasks.",
                "target_resource_type": None,
                "evidence": {
                    "latest_daily_amount": latest_amount,
                    "historical_daily_avg": round(avg_prior, 2),
                    "spike_factor": round(latest_amount / avg_prior, 2),
                    "days_analyzed": len(amounts),
                    "waste_reasons": [
                        f"Latest cost ${latest_amount:.2f} is {latest_amount / avg_prior:.1f}x higher than baseline"
                    ],
                },
                "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

    return recommendations


# ---------------------------------------------------------------------------
# Fleet-Wide Analysis & Summary
# ---------------------------------------------------------------------------

def run_fleet_optimization_analysis(
    servers: list[dict],
    metrics_by_server: dict[str, list[dict]],
    costs_by_server: dict[str, list[dict]],
) -> tuple[list[RecommendationOut], OptimizationSummary]:
    """Run full optimization analysis across all servers in the inventory."""
    all_recommendations: list[RecommendationOut] = []
    total_spend = 0.0
    highest_cost_resources: list[dict[str, Any]] = []

    for s in servers:
        sid = s["id"]
        server_metrics = metrics_by_server.get(sid, [])
        server_costs = costs_by_server.get(sid, [])
        specs = s.get("specifications") or {}
        instance_type = specs.get("type")

        # Compute resource monthly cost
        pricing = get_instance_pricing(instance_type)
        if server_costs:
            res_cost = sum(float(c.get("amount", 0.0)) for c in server_costs)
        elif pricing:
            res_cost = pricing["monthly_cost"]
        else:
            res_cost = 0.0

        total_spend += res_cost
        highest_cost_resources.append({
            "server_id": sid,
            "resource_name": s.get("server_name") or sid,
            "instance_type": instance_type or "unknown",
            "monthly_cost": round(res_cost, 2),
            "region": s.get("aws_region") or "us-east-1",
            "source": s.get("source", "agent"),
        })

        recs = analyze_server_utilization(s, server_metrics, server_costs)
        all_recommendations.extend(recs)

    # Sort highest cost resources descending
    highest_cost_resources.sort(key=lambda r: r["monthly_cost"], reverse=True)

    # Aggregate summary figures
    avoidable_spend = sum(r["estimated_avoidable_cost"] for r in all_recommendations)
    monthly_savings = sum(r["estimated_savings_monthly"] for r in all_recommendations)

    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for r in all_recommendations:
        by_type[r["recommendation_type"]] = by_type.get(r["recommendation_type"], 0) + 1
        by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1

    # Sort recommendations by savings descending
    sorted_recs = sorted(all_recommendations, key=lambda r: r["estimated_savings_monthly"], reverse=True)
    highest_savings_opportunities = [
        {
            "server_id": r["server_id"],
            "resource_name": r["resource_name"],
            "recommendation_type": r["recommendation_type"],
            "severity": r["severity"],
            "monthly_savings": r["estimated_savings_monthly"],
            "action": r["action_recommendation"],
            "confidence": r["confidence"],
        }
        for r in sorted_recs[:5]
    ]

    summary: OptimizationSummary = {
        "total_monthly_spend": round(total_spend, 2),
        "estimated_avoidable_spend": round(avoidable_spend, 2),
        "potential_monthly_savings": round(monthly_savings, 2),
        "total_opportunities_count": len(all_recommendations),
        "highest_cost_resources": highest_cost_resources[:10],
        "highest_savings_opportunities": highest_savings_opportunities,
        "by_type_counts": by_type,
        "by_severity_counts": by_severity,
    }

    return all_recommendations, summary
