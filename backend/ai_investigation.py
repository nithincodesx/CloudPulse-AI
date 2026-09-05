"""CloudPulse AI — Grounded AI Investigation & Recommendation Engine.

Provides automated, plain-English incident investigations and cost waste analyses
grounded strictly in backend-calculated facts (telemetry statistics, rolling/time-aware
baselines, verified AWS On-Demand pricing, and anomaly events).

HONESTY & SAFETY GUARANTEES:
1. The AI model NEVER calculates metrics, sigmas, dollars, or anomalies.
2. All figures in prompts are calculated deterministically by the backend.
3. Prompts strictly forbid fabricating AWS prices, metrics, or estimates.
4. If the LLM is unconfigured, rate-limited, or unavailable, returns a structured,
   deterministic investigation report from raw facts without failing.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional, TypedDict

import httpx
from dotenv import load_dotenv

from insights import (
    DEFAULT_MODELS,
    GEMINI_URL,
    GROQ_URL,
    ai_provider,
)
from logging_conf import get_logger

logger = get_logger("backend.ai_investigation")

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "").strip()


class ActionStep(TypedDict):
    priority: str  # "Critical" | "High" | "Medium" | "Low"
    action: str
    target_resource: str
    rationale: str


class InvestigationReport(TypedDict):
    summary: str
    incident_explanation: str
    cost_impact_explanation: str
    root_cause_hypotheses: list[str]
    prioritized_actions: list[ActionStep]
    grounded_facts: dict[str, Any]
    provider: Optional[str]
    model: Optional[str]
    is_fallback: bool


INVESTIGATION_SYSTEM_PROMPT = """You are CloudPulse AI's Lead Infrastructure & Site Reliability Analyst.
You are investigating an operational incident or cost anomaly using STRICTLY VERIFIED FACTS provided in JSON format.

RULES:
1. Every numerical value (CPU %, RAM %, Network MB, sigma deviation, $ cost, $ savings) MUST come directly from the provided facts. NEVER invent or alter numbers.
2. DO NOT fabricate AWS pricing. If pricing is marked "estimated" or "unpriced", explicitly state that.
3. Explain the incident in clear, concise language (e.g. "CPU is 3.8σ above the Monday 10:00 baseline for 15 minutes").
4. Explain cost waste and underutilization clearly if present.
5. Prioritize actionable next steps into Critical, High, Medium, or Low.
6. Output MUST be valid JSON conforming to the requested schema. Do not include markdown wrappers around the JSON.
"""

INVESTIGATION_SCHEMA_EXAMPLE = """{
  "summary": "Brief 1-2 sentence executive overview.",
  "incident_explanation": "Detailed plain-English explanation of why this was flagged based on telemetry & baselines.",
  "cost_impact_explanation": "Explanation of financial impact, monthly run-rate, and potential savings.",
  "root_cause_hypotheses": [
    "Possible runaway worker loop",
    "Underutilized instance class"
  ],
  "prioritized_actions": [
    {
      "priority": "Critical",
      "action": "Inspect process CPU saturation via top / htop",
      "target_resource": "i-0123456",
      "rationale": "CPU pegged at 95% for 15m"
    }
  ]
}"""


def _sanitize_fact_string(val: Any) -> str:
    """Sanitize strings to prevent prompt injection from server tags/names."""
    if val is None:
        return ""
    s = str(val).replace("\n", " ").replace("\r", " ").replace('"', "'")
    return s[:200]


def build_incident_facts(
    incident: dict,
    server: Optional[dict],
    recent_metrics: list[dict],
    baseline_info: Optional[dict],
    recommendations: list[dict],
) -> dict[str, Any]:
    """Compile structured, sanitized operational facts for an incident investigation."""
    server_dict = server or {}
    specs = server_dict.get("specifications") or {}

    # Telemetry summaries
    cpu_vals = [float(m["cpu_usage"]) for m in recent_metrics if m.get("cpu_usage") is not None]
    ram_vals = [float(m["ram_usage"]) for m in recent_metrics if m.get("ram_usage") is not None]
    net_vals = [float(m["network_traffic"]) for m in recent_metrics if m.get("network_traffic") is not None]

    latest_m = recent_metrics[-1] if recent_metrics else {}

    return {
        "incident": {
            "id": incident.get("id"),
            "title": _sanitize_fact_string(incident.get("title")),
            "type": incident.get("incident_type"),
            "severity": incident.get("severity"),
            "status": incident.get("status"),
            "created_at": incident.get("created_at"),
        },
        "resource": {
            "id": _sanitize_fact_string(server_dict.get("id")),
            "name": _sanitize_fact_string(server_dict.get("server_name")),
            "aws_instance_id": _sanitize_fact_string(server_dict.get("aws_instance_id")),
            "instance_type": _sanitize_fact_string(specs.get("type", "unknown")),
            "region": _sanitize_fact_string(server_dict.get("aws_region", "us-east-1")),
            "vcpus": specs.get("vcpus"),
            "ram_gb": specs.get("ram_gb"),
        },
        "telemetry_stats": {
            "current_cpu_pct": latest_m.get("cpu_usage"),
            "current_ram_pct": latest_m.get("ram_usage"),
            "current_network_mb": latest_m.get("network_traffic"),
            "peak_cpu_pct": max(cpu_vals) if cpu_vals else None,
            "avg_cpu_pct": round(sum(cpu_vals) / len(cpu_vals), 1) if cpu_vals else None,
            "avg_ram_pct": round(sum(ram_vals) / len(ram_vals), 1) if ram_vals else None,
            "sample_count": len(recent_metrics),
        },
        "baseline": baseline_info.get("baselines", {}) if baseline_info else {},
        "cost_recommendations": [
            {
                "type": r.get("recommendation_type"),
                "savings_monthly": r.get("estimated_savings_monthly"),
                "avoidable_cost": r.get("estimated_avoidable_cost"),
                "action": r.get("action_recommendation"),
                "target_type": r.get("target_resource_type"),
                "confidence": r.get("confidence"),
            }
            for r in recommendations[:3]
        ],
    }


def generate_fallback_investigation(facts: dict[str, Any]) -> InvestigationReport:
    """Deterministic, template-based investigation when LLM is unconfigured or unavailable."""
    inc = facts.get("incident", {})
    res = facts.get("resource", {})
    stats = facts.get("telemetry_stats", {})
    recs = facts.get("cost_recommendations", [])

    sev = inc.get("severity", "warning").capitalize()
    title = inc.get("title", "Infrastructure Event")
    res_name = res.get("name") or res.get("id") or "Target Resource"
    cpu = stats.get("current_cpu_pct", "—")
    ram = stats.get("current_ram_pct", "—")

    explanation = (
        f"Incident '{title}' was flagged on {res_name} (type {res.get('instance_type', 'standard')}). "
        f"Latest telemetry observed: CPU {cpu}%, RAM {ram}% across {stats.get('sample_count', 0)} samples."
    )

    cost_explanation = "No direct cost anomalies associated with this incident."
    actions: list[ActionStep] = []

    if recs:
        top_rec = recs[0]
        cost_explanation = (
            f"Cost analysis identified potential monthly savings of ${top_rec.get('savings_monthly', 0.0):.2f}/mo "
            f"via {top_rec.get('type', 'optimization')} ({top_rec.get('confidence', 'MEDIUM')} confidence)."
        )
        actions.append({
            "priority": "High" if sev == "Critical" else "Medium",
            "action": top_rec.get("action", "Review resource sizing"),
            "target_resource": res_name,
            "rationale": f"Identified ${top_rec.get('savings_monthly', 0.0):.2f}/mo avoidable spend",
        })

    actions.append({
        "priority": "Critical" if sev == "Critical" else "Medium",
        "action": f"Inspect active processes and connection health on {res_name}",
        "target_resource": res_name,
        "rationale": f"Resolve {inc.get('type', 'operational')} issue",
    })

    return {
        "summary": f"{sev} severity incident on {res_name} requiring operational review.",
        "incident_explanation": explanation,
        "cost_impact_explanation": cost_explanation,
        "root_cause_hypotheses": [
            f"Unscheduled workload spike or runaway process on {res_name}",
            "Resource misconfiguration or undersized instance class",
        ],
        "prioritized_actions": actions,
        "grounded_facts": facts,
        "provider": None,
        "model": None,
        "is_fallback": True,
    }


def run_ai_incident_investigation(facts: dict[str, Any]) -> InvestigationReport:
    """Investigate an incident using Groq / Gemini with strict factual grounding."""
    provider = ai_provider()
    if not provider:
        logger.info("ai_investigation.skipped_no_provider")
        return generate_fallback_investigation(facts)

    facts_json = json.dumps(facts, indent=2)
    user_prompt = (
        f"Here are the verified operational facts for this incident:\n```json\n{facts_json}\n```\n\n"
        f"Analyze this incident and return ONLY a valid JSON object strictly matching this schema:\n"
        f"{INVESTIGATION_SCHEMA_EXAMPLE}"
    )

    model = AI_MODEL or DEFAULT_MODELS.get(provider, "llama-3.1-8b-instant")

    try:
        if provider == "groq":
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": INVESTIGATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            }
            with httpx.Client(timeout=15.0) as client:
                res = client.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json=payload,
                )
                res.raise_for_status()
                content = res.json()["choices"][0]["message"]["content"]

        elif provider == "gemini":
            url = GEMINI_URL.format(model=model) + f"?key={GEMINI_API_KEY}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": f"{INVESTIGATION_SYSTEM_PROMPT}\n\n{user_prompt}"}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                },
            }
            with httpx.Client(timeout=15.0) as client:
                res = client.post(url, headers={"Content-Type": "application/json"}, json=payload)
                res.raise_for_status()
                content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return generate_fallback_investigation(facts)

        parsed = json.loads(content)
        return {
            "summary": str(parsed.get("summary", "")),
            "incident_explanation": str(parsed.get("incident_explanation", "")),
            "cost_impact_explanation": str(parsed.get("cost_impact_explanation", "")),
            "root_cause_hypotheses": list(parsed.get("root_cause_hypotheses", [])),
            "prioritized_actions": [
                {
                    "priority": str(a.get("priority", "Medium")),
                    "action": str(a.get("action", "")),
                    "target_resource": str(a.get("target_resource", "")),
                    "rationale": str(a.get("rationale", "")),
                }
                for a in parsed.get("prioritized_actions", [])
            ],
            "grounded_facts": facts,
            "provider": provider,
            "model": model,
            "is_fallback": False,
        }

    except Exception as exc:
        logger.warning("ai_investigation.failed_falling_back", error=str(exc))
        fallback = generate_fallback_investigation(facts)
        fallback["summary"] += f" (LLM call failed: {exc})"
        return fallback
