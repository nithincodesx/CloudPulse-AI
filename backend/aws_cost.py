"""AWS Cost Explorer integration for CloudPulse AI.

Read-only: pulls *actual* daily cost per resource tag into the ``daily_costs``
table. Credentials come from ``backend/.env`` (single connected account) and
never touch the database or frontend.

When AWS is not configured, the dashboard reports simulated mode ($0 / connect
prompt) — this module never fabricates cost numbers.

Env vars (all optional; absent ⇒ simulated mode):
    AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  — IAM user/role creds (see README)
    AWS_REGION                                 — default us-east-1
    AWS_COST_TAG_KEY                           — resource-tag key to group by,
                                                 default "server"
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Optional

from dotenv import load_dotenv

from database import (
    get_daily_costs,
    get_latest_cost_date,
    list_servers,
    upsert_daily_cost,
)
from models import CloudStatus, SyncResult

load_dotenv()

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_COST_TAG_KEY = os.getenv("AWS_COST_TAG_KEY", "server").strip()

try:
    import boto3  # noqa: E402
    from botocore.exceptions import BotoCoreError, ClientError
    _BOTO3_AVAILABLE = True
except ImportError:  # pragma: no cover - only when boto3 isn't installed
    boto3 = None
    _BOTO3_AVAILABLE = False


def cloud_configured() -> bool:
    """True when AWS credentials are present and boto3 is installed."""
    return _BOTO3_AVAILABLE and bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)


def get_ce_client():
    """Return a boto3 Cost Explorer client, or raise a clear RuntimeError."""
    if not cloud_configured():
        raise RuntimeError(
            "AWS not configured. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY "
            "in backend/.env (see backend/.env.example and the README) then restart."
        )
    return boto3.client(
        "ce",
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


# ---------------------------------------------------------------------------
# Cost Explorer queries
# ---------------------------------------------------------------------------

def _time_period(days_back: int) -> dict:
    """Daily window ending yesterday (Cost Explorer lags ~24-48h)."""
    today = date.today()
    return {
        "Start": (today - timedelta(days=days_back)).isoformat(),
        "End": today.isoformat(),  # exclusive — includes data through yesterday
    }


def fetch_daily_costs(days_back: int = 14) -> list[dict]:
    """Pull daily UnblendedCost per resource-tag value.

    Returns [{tag_value, date, amount}] — actual AWS spend, never fabricated.
    """
    ce = get_ce_client()
    resp = ce.get_cost_and_usage(
        TimePeriod=_time_period(days_back),
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "TAG", "Key": AWS_COST_TAG_KEY}],
    )

    rows: list[dict] = []
    prefix = f"{AWS_COST_TAG_KEY}$"
    for day in resp.get("ResultsByTime", []):
        day_str = day["TimePeriod"]["Start"]
        for group in day.get("Groups", []):
            # Keys for a TAG grouping come back as ["server$<value>"].
            for key in group.get("Keys", []):
                if not key.startswith(prefix):
                    continue
                tag_value = key[len(prefix):]
                amount = float(group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0.0))
                rows.append({"tag_value": tag_value, "date": day_str, "amount": amount})
    return rows


def fetch_service_breakdown(days_back: int = 14) -> list[dict]:
    """Pull daily UnblendedCost grouped by AWS service.

    Returns [{service, date, amount}] — used for the stacked cost chart.
    """
    ce = get_ce_client()
    resp = ce.get_cost_and_usage(
        TimePeriod=_time_period(days_back),
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    rows: list[dict] = []
    for day in resp.get("ResultsByTime", []):
        day_str = day["TimePeriod"]["Start"]
        for group in day.get("Groups", []):
            service = group.get("Keys", [""])[0]
            amount = float(group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0.0))
            rows.append({"service": service, "date": day_str, "amount": amount})
    return rows


# ---------------------------------------------------------------------------
# Sync / status
# ---------------------------------------------------------------------------

def _match_server(servers: list[dict], tag_value: str) -> Optional[dict]:
    """Map a resource-tag value to a server: cost_tag, then name, then IP."""
    want = tag_value.strip().lower()
    for s in servers:
        if s.get("cost_tag") and s["cost_tag"].strip().lower() == want:
            return s
    for s in servers:
        if s.get("server_name") and s["server_name"].strip().lower() == want:
            return s
    for s in servers:
        if s.get("ip_address") and s["ip_address"].strip().lower() == want:
            return s
    return None


def sync_daily_costs(days_back: int = 14) -> SyncResult:
    """Pull daily costs from Cost Explorer and upsert them into daily_costs."""
    if not cloud_configured():
        return SyncResult(error="AWS not configured — set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in backend/.env")

    servers = list_servers()
    rows = fetch_daily_costs(days_back=days_back)

    matched = 0
    unmatched: set[str] = set()
    total = 0.0
    for row in rows:
        server = _match_server(servers, row["tag_value"])
        if server:
            upsert_daily_cost(
                server_id=server["id"],
                cost_date=row["date"],
                amount=row["amount"],
                currency="USD",
                source="aws_cost_explorer",
            )
            matched += 1
            total += row["amount"]
        else:
            unmatched.add(row["tag_value"])

    # Days actually pulled (distinct dates across all fetched rows).
    days = len({r["date"] for r in rows}) if rows else 0

    return SyncResult(
        days_synced=days,
        matched=matched,
        unmatched=sorted(unmatched),
        total_amount=round(total, 4),
    )


def get_cloud_status() -> CloudStatus:
    """Describe the current cost integration state (never raises on unconfigured)."""
    if not _BOTO3_AVAILABLE:
        return CloudStatus(error="boto3 is not installed — run pip install -r requirements.txt")

    if not cloud_configured():
        return CloudStatus(
            connected=False,
            cost_tag_key=AWS_COST_TAG_KEY,
            cost_source="simulated",
            error="AWS not configured — set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in backend/.env",
        )

    # Probe connectivity once to surface a real error in the UI.
    error: str | None = None
    try:
        get_ce_client()
    except Exception as exc:  # noqa: BLE001 - surface any credential/region error
        error = str(exc)

    rows = get_daily_costs(days=366)
    days_of_data = len({r["cost_date"] for r in rows})

    return CloudStatus(
        connected=error is None,
        provider="aws_cost_explorer",
        cost_tag_key=AWS_COST_TAG_KEY,
        last_sync=get_latest_cost_date(),
        days_of_data=days_of_data,
        cost_source="aws_cost_explorer" if (error is None and days_of_data > 0) else "simulated",
        error=error,
    )


def detect_budget_spikes(server_id: str, days: int = 14, threshold_mult: float = 2.0) -> bool:
    """True when a server's latest daily cost is > threshold_mult × its mean.

    Runs against the *real* daily_costs data — the honest replacement for the
    old per-metric BUDGET_SPIKE heuristic.
    """
    rows = get_daily_costs(server_id=server_id, days=days)
    if len(rows) < 2:
        return False
    amounts = [float(r["amount"]) for r in rows]
    mean = sum(amounts) / len(amounts)
    if mean <= 0:
        return False
    return amounts[-1] > threshold_mult * mean
