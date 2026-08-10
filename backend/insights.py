"""CloudPulse AI — weekly plain-English AI summary.

The scheduled weekly job gathers a week of REAL data (per-server utilization,
real AWS Cost Explorer spend deltas, and alerts), sends it to a free-tier LLM
(Groq or Gemini) that *summarizes* it in plain English, and stores the result.

Honesty contract:
- The LLM is a **summarizer, not a source of numbers** — every figure in the
  prompt comes from telemetry / daily_costs / system_alerts.
- The prompt tells the model that HIGH_CPU/NETWORK_ANOMALY are statistical
  z-scores over a rolling baseline and IDLE_RESOURCE is a low-utilization floor
  — **not ML** — and that Cost Explorer lags 24–48h.
- If no provider is configured, the job reports "LLM not configured" instead of
  inventing a summary.

Env (all optional — with none set, the detector still works, the summary is
skipped):
    AI_PROVIDER=groq|gemini|auto   (auto → Groq if its key is set, else Gemini)
    GROQ_API_KEY=...               (free-tier key from console.groq.com)
    GEMINI_API_KEY=...             (free-tier key from ai.google.dev)
    AI_MODEL=...                   (provider default if unset:
                                    gemini-2.5-flash / llama-3.1-8b-instant)
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from typing import Optional

import httpx
from dotenv import load_dotenv

from anomaly import BASELINE_DAYS, IDLE_CPU_FLOOR, IDLE_RAM_FLOOR
from logging_conf import get_logger
from database import (
    get_daily_costs,
    get_latest_weekly_insight,
    insert_weekly_insight,
    list_alerts,
    list_servers,
    rpc_utilization,
)
from models import InsightGenerateResult, InsightOut

logger = get_logger("backend.insights")

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "").strip().lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "").strip()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODELS = {"groq": "llama-3.1-8b-instant", "gemini": "gemini-2.5-flash"}

# Bounds to keep prompts cheap and token-safe.
MAX_SERVERS = 30
MAX_ALERTS = 15
WEEK_DAYS = 7

SYSTEM_PROMPT = """You are CloudPulse AI's infrastructure analyst. You are given a week of REAL monitoring data and must write a concise plain-English weekly summary for an ops team.

Rules:
- Every number in the input is real: telemetry from the servers, alerts, and AWS Cost Explorer daily spend. Never invent figures, and never claim cost data that is absent.
- How alerts are produced (important context, not rules to repeat):
  * HIGH_CPU and NETWORK_ANOMALY are STATISTICAL z-scores against a rolling 7-day baseline of that server's own history.
  * IDLE_RESOURCE is a low-utilization floor (node underused), not a model prediction.
  * BUDGET_SPIKE means a server's latest daily cost exceeded 2x its 14-day average.
  * None of this is machine learning.
- AWS Cost Explorer lags 24-48h, so the last day or two of spend may be missing from the numbers.
- Output at most 200 words of plain prose. No tables, no markdown headings, no bullet lists.
- Name specific servers and give actionable recommendations: downsize or terminate chronically idle nodes, right-size cost spikes, investigate network/CPU anomalies.
- Quantify when possible (e.g. "db-primary-01 was idle 40% of the time, costing ~$12 for nothing this week").
"""


class LLMError(Exception):
    """Raised when the LLM call fails (bad key, quota, empty response, …)."""


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

def ai_provider() -> Optional[str]:
    """Resolve the LLM provider from env: groq | gemini | None (disabled)."""
    if AI_PROVIDER in ("groq", "gemini"):
        return AI_PROVIDER if (GROQ_API_KEY if AI_PROVIDER == "groq" else GEMINI_API_KEY) else None
    # auto (or unset): Groq first, then Gemini.
    if GROQ_API_KEY:
        return "groq"
    if GEMINI_API_KEY:
        return "gemini"
    return None


def ai_configured() -> bool:
    return ai_provider() is not None


def _model(provider: str) -> str:
    return AI_MODEL or DEFAULT_MODELS[provider]


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------

def _build_context(period_start: date, period_end: date) -> tuple[str, dict]:
    """Collect the week's real data into a bounded prompt context.

    Returns ``(context_text, meta)`` where meta carries server_count,
    alert_count and total_cost for storage.
    """
    servers = list_servers()[:MAX_SERVERS]
    week_start = period_start.isoformat()
    prior_start = (period_start - timedelta(days=WEEK_DAYS)).isoformat()

    server_lines: list[str] = []
    total_cost = 0.0
    for s in servers:
        sid, name = s["id"], s.get("server_name", s["id"])

        # Utilization → "idle X% of the time".
        util = rpc_utilization(sid, BASELINE_DAYS, IDLE_CPU_FLOOR, IDLE_RAM_FLOOR)
        if util and int(util.get("total_samples") or 0) > 0:
            total = int(util["total_samples"])
            idle = int(util.get("idle_samples") or 0)
            idle_pct = round(idle / total * 100, 1)
            avg_cpu = round(float(util.get("avg_cpu") or 0), 1)
            avg_ram = round(float(util.get("avg_ram") or 0), 1)
        else:
            idle_pct = avg_cpu = avg_ram = 0.0

        # Real spend: this week vs prior week (per server — see the
        # get_daily_costs(server_id=...) truncation note in database.py).
        cost_rows = get_daily_costs(server_id=sid, days=2 * WEEK_DAYS)
        this_week = sum(
            float(r["amount"]) for r in cost_rows if r["cost_date"] >= week_start
        )
        prior_week = sum(
            float(r["amount"])
            for r in cost_rows
            if prior_start <= r["cost_date"] < week_start
        )
        delta = this_week - prior_week
        total_cost += this_week

        cost_part = (
            f"cost this week ${this_week:.2f} (prev ${prior_week:.2f}, Δ {delta:+.2f})"
            if cost_rows
            else "cost data unavailable"
        )
        server_lines.append(
            f"- {name}: idle {idle_pct}% of {BASELINE_DAYS}-day window "
            f"(avg CPU {avg_cpu}%, avg RAM {avg_ram}%); {cost_part}"
        )

    # Alerts in the last 7 days.
    alert_lines: list[str] = []
    for a in list_alerts(unresolved_only=False)[:MAX_ALERTS]:
        created = (a.get("created_at") or "")[:10]
        if created < week_start:
            continue
        server_name = (a.get("servers") or {}).get("server_name") or a.get("server_id")
        alert_lines.append(
            f"- {a['alert_type']} on {server_name} ({created}): {a['message']}"
        )

    context = (
        f"WEEK: {period_start.isoformat()} → {period_end.isoformat()} (UTC)\n\n"
        f"SERVERS ({len(server_lines)}):\n"
        + ("\n".join(server_lines) if server_lines else "  (none registered)")
        + f"\n\nALERTS (last {WEEK_DAYS} days, {len(alert_lines)}):\n"
        + ("\n".join(alert_lines) if alert_lines else "  (no alerts)")
        + f"\n\nTOTAL WEEKLY SPEND: ${total_cost:.2f}"
    )

    meta = {
        "server_count": len(server_lines),
        "alert_count": len(alert_lines),
        "total_cost": round(total_cost, 2),
    }
    return context, meta


# ---------------------------------------------------------------------------
# LLM calls (httpx only — no extra SDKs)
# ---------------------------------------------------------------------------

def _call_groq(prompt: str, model: str) -> str:
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_completion_tokens": 600,
            },
        )
    if resp.status_code != 200:
        raise LLMError(f"Groq API error {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected Groq response shape: {resp.text[:300]}") from exc


def _call_gemini(prompt: str, model: str) -> str:
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            GEMINI_URL.format(model=model),
            params={"key": GEMINI_API_KEY},
            json={"contents": [{"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + prompt}]}]},
        )
    if resp.status_code != 200:
        raise LLMError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0].get("text")
    except (KeyError, IndexError, TypeError) as exc:
        reason = data.get("candidates", [{}])[0].get("finishReason", "unknown")
        raise LLMError(f"Gemini returned no content (finishReason={reason})") from exc
    if not text:
        raise LLMError("Gemini returned an empty summary.")
    return text.strip()


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate_weekly_summary() -> InsightGenerateResult:
    """Build the week's summary, call the LLM, persist it. Never raises.

    Returns an InsightGenerateResult: ``generated=True`` with the stored
    InsightOut on success, or ``generated=False`` with a human-readable error.
    """
    provider = ai_provider()
    if not provider:
        return InsightGenerateResult(
            generated=False,
            error=(
                "LLM not configured — set GROQ_API_KEY or GEMINI_API_KEY in "
                "backend/.env (see backend/.env.example) to enable AI summaries."
            ),
        )

    period_end = date.today()
    period_start = period_end - timedelta(days=WEEK_DAYS - 1)

    try:
        context, meta = _build_context(period_start, period_end)
        t0 = time.perf_counter()
        if provider == "groq":
            summary = _call_groq(context, _model("groq"))
        else:
            summary = _call_gemini(context, _model("gemini"))
        generation_ms = int((time.perf_counter() - t0) * 1000)
    except LLMError as exc:
        return InsightGenerateResult(generated=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - never let the scheduler die
        return InsightGenerateResult(generated=False, error=f"Summary generation failed: {exc}")

    meta["generation_ms"] = generation_ms
    row = insert_weekly_insight(
        {
            "summary": summary,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "provider": provider,
            "model": _model(provider),
            "meta": json.dumps(meta),
        }
    )
    return InsightGenerateResult(generated=True, insight=InsightOut(**row))


def get_latest_summary() -> Optional[InsightOut]:
    """Return the most recent stored weekly summary (or None)."""
    row = get_latest_weekly_insight()
    return InsightOut(**row) if row else None


def run_weekly_job() -> None:
    """APScheduler entrypoint — logs, never raises."""
    try:
        result = generate_weekly_summary()
        if result.generated:
            logger.info(
                "weekly_summary.stored",
                provider=result.insight.provider,
                model=result.insight.model,
                period_start=result.insight.period_start.isoformat(),
                period_end=result.insight.period_end.isoformat(),
            )
        else:
            logger.warning("weekly_summary.skipped", error=result.error)
    except Exception as exc:  # noqa: BLE001 - a failed run must not kill the scheduler thread
        logger.warning("weekly_summary.job_failed", error=str(exc))
