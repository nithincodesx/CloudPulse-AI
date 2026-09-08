"""AWS Cost Explorer integration for CloudPulse AI.

Read-only: pulls *actual* daily cost per resource tag into the ``daily_costs``
table. Supports Multi-Tenant cross-account AssumeRole connections as well as
local developer .env fallback.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Optional

from dotenv import load_dotenv

from aws_credentials import get_aws_client
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
AWS_REGION = os.getenv("AWS_REGION", "us-east-1").strip()
AWS_COST_TAG_KEY = os.getenv("AWS_COST_TAG_KEY", "server").strip()

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    _BOTO3_AVAILABLE = True
except ImportError:  # pragma: no cover
    boto3 = None
    _BOTO3_AVAILABLE = False


def cloud_configured(connection: Optional[dict[str, Any]] = None) -> bool:
    """True when an active AWS connection or developer credentials are present and boto3 is installed."""
    if not _BOTO3_AVAILABLE:
        return False
    if connection and connection.get("role_arn") and connection.get("external_id"):
        return True
    return bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)


def get_ce_client(connection: Optional[dict[str, Any]] = None, region: Optional[str] = None):
    """Return a boto3 Cost Explorer client, or raise a clear RuntimeError."""
    if not cloud_configured(connection):
        raise RuntimeError(
            "AWS not configured. Connect an AWS Account in Dashboard or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in backend/.env."
        )
    return get_aws_client("ce", connection=connection, region=region or AWS_REGION)


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


def fetch_daily_costs(days_back: int = 14, connection: Optional[dict[str, Any]] = None) -> list[dict]:
    """Pull daily UnblendedCost per resource-tag value.

    Returns [{tag_value, date, amount}] — actual AWS spend, never fabricated.
    """
    ce = get_ce_client(connection=connection)
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


def fetch_service_breakdown(days_back: int = 14, connection: Optional[dict[str, Any]] = None) -> list[dict]:
    """Pull daily UnblendedCost grouped by AWS service.

    Returns [{service, date, amount}] — used for the stacked cost chart.
    """
    ce = get_ce_client(connection=connection)
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


def sync_daily_costs(
    days_back: int = 14,
    connection: Optional[dict[str, Any]] = None,
) -> SyncResult:
    """Pull daily costs from Cost Explorer and upsert them into daily_costs."""
    if not cloud_configured(connection):
        return SyncResult(error="AWS not configured — Connect an AWS account in the dashboard.")

    servers = list_servers()
    try:
        rows = fetch_daily_costs(days_back=days_back, connection=connection)
    except Exception as exc:  # noqa: BLE001
        return SyncResult(error=f"Cost Explorer error: {exc}")

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


def get_cloud_status(connection: Optional[dict[str, Any]] = None) -> CloudStatus:
    """Describe the current cost integration state (never raises on unconfigured)."""
    if not _BOTO3_AVAILABLE:
        return CloudStatus(error="boto3 is not installed — run pip install -r requirements.txt")

    if not cloud_configured(connection):
        return CloudStatus(
            connected=False,
            cost_tag_key=AWS_COST_TAG_KEY,
            cost_source="simulated",
            error="AWS not configured — Connect an AWS account in the dashboard.",
        )

    # Probe connectivity once to surface a real error in the UI.
    error: str | None = None
    try:
        get_ce_client(connection=connection)
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
    """True when a server's latest daily cost is > threshold_mult × its mean."""
    rows = get_daily_costs(server_id=server_id, days=days)
    if len(rows) < 2:
        return False
    amounts = [float(r["amount"]) for r in rows]
    mean = sum(amounts) / len(amounts)
    if mean <= 0:
        return False
    return amounts[-1] > threshold_mult * mean


# ---------------------------------------------------------------------------
# Cost Intelligence: Account, Service, Region, Trends
# ---------------------------------------------------------------------------


def fetch_region_breakdown(days_back: int = 14, connection: Optional[dict[str, Any]] = None) -> list[dict]:
    """Pull daily UnblendedCost grouped by AWS region.

    Returns [{region, date, amount}] — used for region cost analysis.
    """
    ce = get_ce_client(connection=connection)
    resp = ce.get_cost_and_usage(
        TimePeriod=_time_period(days_back),
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "REGION"}],
    )

    rows: list[dict] = []
    for day in resp.get("ResultsByTime", []):
        day_str = day["TimePeriod"]["Start"]
        for group in day.get("Groups", []):
            region = group.get("Keys", [""])[0]
            amount = float(group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0.0))
            rows.append({"region": region, "date": day_str, "amount": amount})
    return rows


def fetch_account_breakdown(days_back: int = 14, connection: Optional[dict[str, Any]] = None) -> list[dict]:
    """Pull daily UnblendedCost grouped by AWS account (for organizations with multiple accounts).

    Returns [{account_id, date, amount}] — used for multi-account cost analysis.
    """
    ce = get_ce_client(connection=connection)
    resp = ce.get_cost_and_usage(
        TimePeriod=_time_period(days_back),
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}],
    )

    rows: list[dict] = []
    for day in resp.get("ResultsByTime", []):
        day_str = day["TimePeriod"]["Start"]
        for group in day.get("Groups", []):
            account = group.get("Keys", [""])[0]
            amount = float(group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0.0))
            rows.append({"account_id": account, "date": day_str, "amount": amount})
    return rows


def get_cost_trends(server_id: str, days: int = 30) -> dict[str, Any]:
    """Compute cost trends for a server: daily, monthly, actual vs estimated.

    Returns structured trend data with clear labeling of actual vs estimated costs.
    """
    costs = get_daily_costs(server_id=server_id, days=days)
    if not costs:
        return {
            "server_id": server_id,
            "days_analyzed": 0,
            "daily_costs": [],
            "monthly_actual": 0.0,
            "monthly_estimated": 0.0,
            "trend_direction": "stable",
            "cost_source": "none",
        }

    amounts = [float(c.get("amount", 0.0)) for c in costs]
    dates = [c.get("date", "") for c in costs]

    # Actual cost from AWS Cost Explorer
    monthly_actual = round(sum(amounts), 2)

    # Trend direction: compare first half vs second half
    mid = len(amounts) // 2
    if mid > 0:
        first_half_avg = sum(amounts[:mid]) / mid
        second_half_avg = sum(amounts[mid:]) / (len(amounts) - mid)
        if second_half_avg > first_half_avg * 1.2:
            trend = "increasing"
        elif second_half_avg < first_half_avg * 0.8:
            trend = "decreasing"
        else:
            trend = "stable"
    else:
        trend = "stable"

    # Determine cost source
    cost_source = "aws_cost_explorer" if costs and costs[0].get("source") == "aws_cost_explorer" else "estimated"

    return {
        "server_id": server_id,
        "days_analyzed": len(amounts),
        "daily_costs": [{"date": d, "amount": a} for d, a in zip(dates, amounts)],
        "monthly_actual": monthly_actual,
        "monthly_estimated": monthly_actual,  # Same as actual when from Cost Explorer
        "trend_direction": trend,
        "cost_source": cost_source,
    }


def detect_cost_anomalies(server_id: str, days: int = 14, z_threshold: float = 2.5) -> list[dict]:
    """Detect cost anomalies using statistical methods on daily cost data.

    Returns list of anomaly events with severity, deviation, and evidence.
    """
    costs = get_daily_costs(server_id=server_id, days=days)
    if len(costs) < 7:
        return []

    amounts = [float(c.get("amount", 0.0)) for c in costs if c.get("amount") is not None]
    if len(amounts) < 7:
        return []

    # Calculate mean and std
    mean = sum(amounts) / len(amounts)
    if mean < 0.01:
        return []

    variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
    std = variance ** 0.5

    if std < 0.01:
        return []

    anomalies = []
    for i, (cost, amount) in enumerate(zip(costs, amounts)):
        z = (amount - mean) / std
        if abs(z) >= z_threshold:
            severity = "critical" if abs(z) >= 4.0 else "warning"
            anomalies.append({
                "date": cost.get("date", ""),
                "amount": amount,
                "baseline_avg": round(mean, 2),
                "deviation_sigma": round(z, 2),
                "severity": severity,
                "direction": "spike" if z > 0 else "drop",
            })

    return anomalies
