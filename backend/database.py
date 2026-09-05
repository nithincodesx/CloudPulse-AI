"""Supabase (Postgres) database client and query helpers for CloudPulse AI.

The schema lives in ``supabase-schema.sql`` and is applied once in the
Supabase SQL Editor. This module talks to it over PostgREST via the
supabase-py client — there is no local database and no SQLite.

The backend uses the **service-role key**, which bypasses Row Level
Security; RLS (`auth.uid() = owner_id`) protects the tables from direct
anon-key access by the frontend. The service key never leaves the backend.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

from logging_conf import get_logger

logger = get_logger("backend.database")

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set. Copy backend/.env.example "
        "to backend/.env and fill them in, then apply supabase-schema.sql in "
        "the Supabase SQL Editor."
    )

try:
    _supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
except Exception as exc:
    raise RuntimeError(
        "Could not initialize the Supabase client from SUPABASE_URL/SUPABASE_SERVICE_KEY. "
        "Verify the credentials in backend/.env (see backend/.env.example). "
        f"({exc})"
    ) from exc


def init_db():
    """Verify Supabase connectivity and that the schema has been applied.

    Tables are created by running ``supabase-schema.sql`` in the Supabase SQL
    Editor — DDL cannot be executed over the PostgREST API.
    """
    try:
        _supabase.table("servers").select("id").limit(1).execute()
        logger.info("db.connected", provider="supabase")
    except Exception as exc:
        raise RuntimeError(
            "Could not reach Supabase. Check SUPABASE_URL/SUPABASE_SERVICE_KEY and "
            "that supabase-schema.sql has been applied in the SQL Editor. "
            f"({exc})"
        ) from exc


def db_ping() -> bool:
    """Lightweight connectivity check for /health. Never raises."""
    try:
        _supabase.table("servers").select("id").limit(1).execute()
        return True
    except Exception as exc:  # noqa: BLE001 - health endpoint must not 500
        logger.warning("health.db_ping.failed", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------

def list_servers(status_filter: Optional[str] = None) -> list[dict]:
    """Return all servers, optionally filtered by status."""
    query = _supabase.table("servers").select("*")
    if status_filter:
        query = query.eq("status", status_filter)
    return query.execute().data


def get_server(server_id: str) -> Optional[dict]:
    """Return a single server by id (None when missing)."""
    return (
        _supabase.table("servers")
        .select("*")
        .eq("id", server_id)
        .maybe_single()
        .execute()
        .data
    )


def get_server_by_token(token: str) -> Optional[dict]:
    """Return the server that owns the given ingestion token (None when unknown)."""
    return (
        _supabase.table("servers")
        .select("*")
        .eq("ingestion_token", token)
        .maybe_single()
        .execute()
        .data
    )


def get_server_by_aws_instance_id(aws_instance_id: str) -> Optional[dict]:
    """Return the server associated with an AWS instance ID (None when missing)."""
    if not aws_instance_id:
        return None
    return (
        _supabase.table("servers")
        .select("*")
        .eq("aws_instance_id", aws_instance_id)
        .maybe_single()
        .execute()
        .data
    )


def upsert_discovered_server(payload: dict) -> dict:
    """Insert or update a discovered AWS server row in the servers table."""
    data = dict(payload)
    if "id" in data:
        server_id = data.pop("id")
        _supabase.table("servers").update(data).eq("id", server_id).execute()
        return get_server(server_id) or {}
    else:
        if "id" not in data:
            data["id"] = str(uuid.uuid4())
        if "ingestion_token" not in data:
            data["ingestion_token"] = os.urandom(16).hex()
        rows = _supabase.table("servers").insert(data).execute().data
        return rows[0] if rows else {}


def update_server_status(server_id: str, status: str) -> dict:
    """Update a server's status field (active, warning, critical, idle)."""
    _supabase.table("servers").update({"status": status}).eq("id", server_id).execute()
    return get_server(server_id)



# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def insert_metric(payload: dict) -> dict:
    """Insert a new server_metrics row."""
    if "id" not in payload:
        payload["id"] = str(uuid.uuid4())
    if "recorded_at" not in payload:
        payload["recorded_at"] = datetime.now(timezone.utc).isoformat()

    rows = _supabase.table("server_metrics").insert(payload).execute().data
    return rows[0]


def latest_metrics(server_id: str, limit: int = 10) -> list[dict]:
    """Return the *limit* most-recent metric rows for a server in chronological order."""
    rows = (
        _supabase.table("server_metrics")
        .select("*")
        .eq("server_id", server_id)
        .order("recorded_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )
    rows.reverse()  # PostgREST returns newest-first; reorder to chronological
    return rows


def rpc_baseline(server_id: str, days: int) -> dict | None:
    """Run the ``metrics_baseline`` aggregate (7-day mean/stddev per metric).

    Returns ``None`` when the function is unavailable or returns no rows — the
    caller must treat that as "no baseline, make no anomaly claims" rather than
    erroring. Never raises.
    """
    try:
        rows = _supabase.rpc(
            "metrics_baseline",
            {"p_server_id": server_id, "p_days": days},
        ).execute().data
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on missing RPC
        logger.warning("rpc.metrics_baseline.failed", error=str(exc))
        return None
    if not rows:
        return None
    return rows[0]


def rpc_utilization(server_id: str, days: int, cpu_floor: float, ram_floor: float) -> dict | None:
    """Run the ``metrics_utilization`` aggregate (idle-sample fraction over a window)."""
    try:
        rows = _supabase.rpc(
            "metrics_utilization",
            {
                "p_server_id": server_id,
                "p_days": days,
                "p_cpu_floor": cpu_floor,
                "p_ram_floor": ram_floor,
            },
        ).execute().data
    except Exception as exc:  # noqa: BLE001
        logger.warning("rpc.metrics_utilization.failed", error=str(exc))
        return None
    if not rows:
        return None
    return rows[0]


# ---------------------------------------------------------------------------
# Daily costs (real spend, from AWS Cost Explorer)
# ---------------------------------------------------------------------------

def upsert_daily_cost(server_id: str, cost_date: str, amount: float,
                      currency: str = "USD", source: str = "aws_cost_explorer") -> None:
    """Insert or update one daily cost row (unique on server_id + cost_date)."""
    _supabase.table("daily_costs").upsert(
        {
            "server_id": server_id,
            "cost_date": cost_date,
            "amount": amount,
            "currency": currency,
            "source": source,
        },
        on_conflict="server_id,cost_date",
    ).execute()


def get_daily_costs(server_id: str | None = None, days: int = 30) -> list[dict]:
    """Return daily cost rows, oldest first. Optionally filtered to one server."""
    query = _supabase.table("daily_costs").select("*")
    if server_id:
        query = query.eq("server_id", server_id)
    rows = query.order("cost_date", desc=True).limit(days).execute().data
    rows.reverse()  # PostgREST returns newest-first; reorder to chronological
    return rows


def get_daily_cost_totals(days: int = 30) -> list[dict]:
    """Per-server daily cost aggregates for the last *days* days.

    Returns rows like {server_id, amount, cost_date, currency, source} —
    the amount is the raw daily value; aggregation happens in the API layer.
    """
    return get_daily_costs(server_id=None, days=days)


def get_latest_cost_date() -> str | None:
    """Return the most recent cost_date present in daily_costs (or None)."""
    rows = (
        _supabase.table("daily_costs")
        .select("cost_date")
        .order("cost_date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0]["cost_date"] if rows else None


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def list_alerts(unresolved_only: bool = True) -> list[dict]:
    """Return alerts, newest first, with the owning server's name embedded."""
    query = _supabase.table("system_alerts").select("*, servers(server_name)")
    if unresolved_only:
        query = query.eq("resolved", False)
    rows = query.order("created_at", desc=True).execute().data

    formatted = []
    for r in rows:
        alert = dict(r)
        # PostgREST embeds the joined server as a nested 'servers' object.
        embedded = alert.pop("servers", None)
        server_name = embedded.get("server_name") if embedded else None
        alert["servers"] = {"server_name": server_name} if server_name else None
        alert["resolved"] = bool(alert["resolved"])
        formatted.append(alert)

    return formatted


def insert_alert(payload: dict) -> dict:
    """Write a new system_alerts row."""
    if "id" not in payload:
        payload["id"] = str(uuid.uuid4())
    if "created_at" not in payload:
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
    if "resolved" not in payload:
        payload["resolved"] = False

    row = _supabase.table("system_alerts").insert(payload).execute().data[0]
    row["resolved"] = bool(row["resolved"])
    return row


def resolve_alert(alert_id: str) -> dict:
    """Mark an alert as resolved. Returns the updated row, or {} when missing."""
    _supabase.table("system_alerts").update({"resolved": True}).eq("id", alert_id).execute()

    row = (
        _supabase.table("system_alerts")
        .select("*")
        .eq("id", alert_id)
        .maybe_single()
        .execute()
        .data
    )
    if row:
        row["resolved"] = bool(row["resolved"])
        return row
    return {}


# ---------------------------------------------------------------------------
# Weekly AI insights
# ---------------------------------------------------------------------------

def insert_weekly_insight(payload: dict) -> dict:
    """Upsert a weekly insight (idempotent on period_start + period_end)."""
    if "id" not in payload:
        payload["id"] = str(uuid.uuid4())
    row = (
        _supabase.table("weekly_insights")
        .upsert(payload, on_conflict="period_start,period_end")
        .execute()
        .data[0]
    )
    return row


def get_latest_weekly_insight() -> dict | None:
    """Return the most recently generated weekly insight (or None)."""
    rows = (
        _supabase.table("weekly_insights")
        .select("*")
        .order("generated_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Phase 2: Anomaly Events
# ---------------------------------------------------------------------------

def insert_anomaly_event(payload: dict) -> dict:
    """Record an anomaly event in anomaly_events."""
    data = dict(payload)
    if "id" not in data:
        data["id"] = str(uuid.uuid4())
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()
    if "resolved" not in data:
        data["resolved"] = False

    try:
        rows = _supabase.table("anomaly_events").insert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.insert_anomaly_event.fallback", error=str(exc))
        return data


def list_anomaly_events(
    server_id: Optional[str] = None,
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    limit: int = 50,
) -> list[dict]:
    """Return anomaly events, newest first, with optional filters."""
    try:
        query = _supabase.table("anomaly_events").select("*, servers(server_name)")
        if server_id:
            query = query.eq("server_id", server_id)
        if severity:
            query = query.eq("severity", severity)
        if resolved is not None:
            query = query.eq("resolved", resolved)

        rows = query.order("created_at", desc=True).limit(limit).execute().data
        formatted = []
        for r in rows:
            event = dict(r)
            embedded = event.pop("servers", None)
            server_name = embedded.get("server_name") if embedded else None
            event["servers"] = {"server_name": server_name} if server_name else None
            event["resolved"] = bool(event.get("resolved", False))
            formatted.append(event)
        return formatted
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_anomaly_events.failed", error=str(exc))
        return []


def resolve_anomaly_event(event_id: str) -> dict:
    """Mark an anomaly event as resolved."""
    try:
        _supabase.table("anomaly_events").update({"resolved": True}).eq("id", event_id).execute()
        row = _supabase.table("anomaly_events").select("*").eq("id", event_id).maybe_single().execute().data
        return row or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.resolve_anomaly_event.failed", error=str(exc))
        return {}


# ---------------------------------------------------------------------------
# Phase 2: Cost Optimization Recommendations
# ---------------------------------------------------------------------------

def upsert_optimization_recommendations(recommendations: list[dict]) -> int:
    """Bulk upsert or insert optimization recommendations."""
    if not recommendations:
        return 0

    inserted_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for rec in recommendations:
        payload = dict(rec)
        server_id = payload.get("server_id")
        rec_type = payload.get("recommendation_type")
        payload["updated_at"] = now_iso

        try:
            # Check if active recommendation of same type exists for this server
            existing = (
                _supabase.table("optimization_recommendations")
                .select("id")
                .eq("server_id", server_id)
                .eq("recommendation_type", rec_type)
                .eq("status", "active")
                .maybe_single()
                .execute()
                .data
            )
            if existing:
                rec_id = existing["id"]
                _supabase.table("optimization_recommendations").update(payload).eq("id", rec_id).execute()
            else:
                if "id" not in payload or not payload["id"]:
                    payload["id"] = str(uuid.uuid4())
                if "created_at" not in payload:
                    payload["created_at"] = now_iso
                _supabase.table("optimization_recommendations").insert(payload).execute()
            inserted_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("db.upsert_optimization_recommendations.item_failed", error=str(exc))

    return inserted_count


def list_optimization_recommendations(
    server_id: Optional[str] = None,
    service_name: Optional[str] = None,
    region: Optional[str] = None,
    severity: Optional[str] = None,
    recommendation_type: Optional[str] = None,
    status: Optional[str] = "active",
    limit: int = 50,
) -> list[dict]:
    """Fetch optimization recommendations matching filters."""
    try:
        query = _supabase.table("optimization_recommendations").select("*, servers(server_name)")
        if server_id:
            query = query.eq("server_id", server_id)
        if service_name:
            query = query.eq("service_name", service_name)
        if region:
            query = query.eq("region", region)
        if severity:
            query = query.eq("severity", severity)
        if recommendation_type:
            query = query.eq("recommendation_type", recommendation_type)
        if status:
            query = query.eq("status", status)

        rows = query.order("estimated_savings_monthly", desc=True).limit(limit).execute().data
        formatted = []
        for r in rows:
            rec = dict(r)
            embedded = rec.pop("servers", None)
            server_name = embedded.get("server_name") if embedded else None
            rec["servers"] = {"server_name": server_name} if server_name else None
            formatted.append(rec)
        return formatted
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_optimization_recommendations.failed", error=str(exc))
        return []


def update_optimization_recommendation_status(recommendation_id: str, status: str) -> dict:
    """Update recommendation status ('active', 'applied', 'dismissed')."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        _supabase.table("optimization_recommendations").update(
            {"status": status, "updated_at": now_iso}
        ).eq("id", recommendation_id).execute()

        row = (
            _supabase.table("optimization_recommendations")
            .select("*")
            .eq("id", recommendation_id)
            .maybe_single()
            .execute()
            .data
        )
        return row or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.update_optimization_recommendation_status.failed", error=str(exc))
        return {}


# ---------------------------------------------------------------------------
# Phase 3: Notification Channels
# ---------------------------------------------------------------------------

def list_notification_channels() -> list[dict]:
    """Return all registered notification channels."""
    try:
        return _supabase.table("notification_channels").select("*").order("created_at", desc=False).execute().data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_notification_channels.failed", error=str(exc))
        return []


def upsert_notification_channel(payload: dict) -> dict:
    """Insert or update a notification channel."""
    data = dict(payload)
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()

    try:
        rows = _supabase.table("notification_channels").upsert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.upsert_notification_channel.failed", error=str(exc))
        return data


def delete_notification_channel(channel_id: str) -> bool:
    """Delete a notification channel."""
    try:
        _supabase.table("notification_channels").delete().eq("id", channel_id).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.delete_notification_channel.failed", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Phase 3: Alert Rules
# ---------------------------------------------------------------------------

def list_alert_rules() -> list[dict]:
    """Return all alert rules."""
    try:
        return _supabase.table("alert_rules").select("*").order("created_at", desc=False).execute().data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_alert_rules.failed", error=str(exc))
        return []


def upsert_alert_rule(payload: dict) -> dict:
    """Insert or update an alert rule."""
    data = dict(payload)
    now_iso = datetime.now(timezone.utc).isoformat()
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())
    if "created_at" not in data:
        data["created_at"] = now_iso
    data["updated_at"] = now_iso

    try:
        rows = _supabase.table("alert_rules").upsert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.upsert_alert_rule.failed", error=str(exc))
        return data


def delete_alert_rule(rule_id: str) -> bool:
    """Delete an alert rule."""
    try:
        _supabase.table("alert_rules").delete().eq("id", rule_id).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.delete_alert_rule.failed", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Phase 3: Notification Logs
# ---------------------------------------------------------------------------

def insert_notification_log(payload: dict) -> dict:
    """Insert a delivery log row."""
    data = dict(payload)
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()
    try:
        rows = _supabase.table("notification_logs").insert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.insert_notification_log.failed", error=str(exc))
        return data


def list_notification_logs(incident_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Fetch recent notification logs."""
    try:
        q = _supabase.table("notification_logs").select("*")
        if incident_id:
            q = q.eq("incident_id", incident_id)
        return q.order("created_at", desc=True).limit(limit).execute().data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_notification_logs.failed", error=str(exc))
        return []


# ---------------------------------------------------------------------------
# Phase 3: Incidents & Timeline
# ---------------------------------------------------------------------------

def create_or_update_incident(payload: dict) -> dict:
    """Insert or update an incident."""
    data = dict(payload)
    now_iso = datetime.now(timezone.utc).isoformat()
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())
    if "created_at" not in data:
        data["created_at"] = now_iso
    data["updated_at"] = now_iso

    try:
        rows = _supabase.table("incidents").upsert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.create_or_update_incident.failed", error=str(exc))
        return data


def list_incidents(status_filter: Optional[str] = None, limit: int = 50) -> list[dict]:
    """List incidents with embedded server names."""
    try:
        q = _supabase.table("incidents").select("*, servers(server_name)")
        if status_filter and status_filter != "all":
            q = q.eq("status", status_filter)
        rows = q.order("created_at", desc=True).limit(limit).execute().data

        formatted = []
        for r in rows:
            inc = dict(r)
            embedded = inc.pop("servers", None)
            server_name = embedded.get("server_name") if embedded else None
            inc["servers"] = {"server_name": server_name} if server_name else None
            formatted.append(inc)
        return formatted
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_incidents.failed", error=str(exc))
        return []


def get_incident(incident_id: str) -> Optional[dict]:
    """Fetch a single incident by ID."""
    try:
        row = (
            _supabase.table("incidents")
            .select("*, servers(server_name, specifications, aws_region, aws_instance_id)")
            .eq("id", incident_id)
            .maybe_single()
            .execute()
            .data
        )
        if not row:
            return None
        inc = dict(row)
        embedded = inc.pop("servers", None)
        inc["server_details"] = embedded
        return inc
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_incident.failed", error=str(exc))
        return None


def update_incident_status(
    incident_id: str,
    new_status: str,
    actor: str = "Operator",
    resolution_notes: Optional[str] = None,
) -> Optional[dict]:
    """Transition incident status (open -> acknowledged -> resolved)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    update_data: dict[str, Any] = {"status": new_status, "updated_at": now_iso}

    if new_status == "acknowledged":
        update_data["acknowledged_at"] = now_iso
        update_data["acknowledged_by"] = actor
    elif new_status == "resolved":
        update_data["resolved_at"] = now_iso
        update_data["resolved_by"] = actor
        if resolution_notes:
            update_data["root_cause_summary"] = resolution_notes

    try:
        _supabase.table("incidents").update(update_data).eq("id", incident_id).execute()
        return get_incident(incident_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.update_incident_status.failed", error=str(exc))
        return None


def insert_incident_timeline_event(payload: dict) -> dict:
    """Record an event in incident_timeline."""
    data = dict(payload)
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()
    try:
        rows = _supabase.table("incident_timeline").insert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.insert_incident_timeline_event.failed", error=str(exc))
        return data


def list_incident_timeline(incident_id: str) -> list[dict]:
    """Fetch chronological timeline for an incident."""
    try:
        return (
            _supabase.table("incident_timeline")
            .select("*")
            .eq("incident_id", incident_id)
            .order("created_at", desc=False)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_incident_timeline.failed", error=str(exc))
        return []


def insert_incident_note(payload: dict) -> dict:
    """Add a note to an incident."""
    data = dict(payload)
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()
    try:
        rows = _supabase.table("incident_notes").insert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.insert_incident_note.failed", error=str(exc))
        return data


def list_incident_notes(incident_id: str) -> list[dict]:
    """Fetch all notes on an incident."""
    try:
        return (
            _supabase.table("incident_notes")
            .select("*")
            .eq("incident_id", incident_id)
            .order("created_at", desc=False)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_incident_notes.failed", error=str(exc))
        return []


# ---------------------------------------------------------------------------
# Phase 4: Multi-Tenant AWS Connections
# ---------------------------------------------------------------------------

def create_aws_connection(payload: dict) -> dict:
    """Insert a new AWS connection."""
    data = dict(payload)
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    if "created_at" not in data:
        data["created_at"] = now_iso
    data["updated_at"] = now_iso

    try:
        rows = _supabase.table("aws_connections").insert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.create_aws_connection.failed", error=str(exc))
        return data


def get_aws_connection(connection_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Fetch a single AWS connection by ID (optionally scoped to user)."""
    try:
        q = _supabase.table("aws_connections").select("*").eq("id", connection_id)
        if user_id:
            q = q.eq("user_id", user_id)
        return q.maybe_single().execute().data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_aws_connection.failed", error=str(exc))
        return None


def list_aws_connections(user_id: Optional[str] = None) -> list[dict]:
    """List AWS connections (optionally filtered by user_id)."""
    try:
        q = _supabase.table("aws_connections").select("*")
        if user_id:
            q = q.eq("user_id", user_id)
        return q.order("created_at", desc=True).execute().data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_aws_connections.failed", error=str(exc))
        return []


def update_aws_connection(connection_id: str, updates: dict) -> Optional[dict]:
    """Update fields of an AWS connection."""
    data = dict(updates)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        _supabase.table("aws_connections").update(data).eq("id", connection_id).execute()
        return get_aws_connection(connection_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.update_aws_connection.failed", error=str(exc))
        return None


def delete_aws_connection(connection_id: str, user_id: Optional[str] = None) -> bool:
    """Delete an AWS connection."""
    try:
        q = _supabase.table("aws_connections").delete().eq("id", connection_id)
        if user_id:
            q = q.eq("user_id", user_id)
        q.execute()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.delete_aws_connection.failed", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Phase 5: Organizations, RBAC, Audit Logs & Scoped Queries
# ---------------------------------------------------------------------------

def create_organization(payload: dict) -> dict:
    """Insert a new organization record."""
    data = dict(payload)
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    if "created_at" not in data:
        data["created_at"] = now_iso
    data["updated_at"] = now_iso

    try:
        rows = _supabase.table("organizations").insert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.create_organization.failed", error=str(exc))
        return data


def get_organization_by_id(org_id: str) -> Optional[dict]:
    """Retrieve an organization by its ID."""
    try:
        return (
            _supabase.table("organizations")
            .select("*")
            .eq("id", org_id)
            .maybe_single()
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_organization_by_id.failed", error=str(exc))
        return None


def get_organization_by_slug(slug: str) -> Optional[dict]:
    """Retrieve an organization by slug."""
    try:
        return (
            _supabase.table("organizations")
            .select("*")
            .eq("slug", slug)
            .maybe_single()
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_organization_by_slug.failed", error=str(exc))
        return None


def list_organizations_for_user(user_id: str) -> list[dict]:
    """Return all organizations that a user belongs to, including their role."""
    try:
        memberships = (
            _supabase.table("organization_members")
            .select("organization_id, role, created_at")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        if not memberships:
            return []

        org_ids = [m["organization_id"] for m in memberships]
        orgs = (
            _supabase.table("organizations")
            .select("*")
            .in_("id", org_ids)
            .execute()
            .data
        )

        role_map = {m["organization_id"]: m["role"] for m in memberships}
        for o in orgs:
            o["user_role"] = role_map.get(o["id"], "MEMBER")

        return orgs
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_organizations_for_user.failed", error=str(exc))
        return []


def update_organization(org_id: str, updates: dict) -> Optional[dict]:
    """Update organization settings."""
    data = dict(updates)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        _supabase.table("organizations").update(data).eq("id", org_id).execute()
        return get_organization_by_id(org_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.update_organization.failed", error=str(exc))
        return None


def delete_organization(org_id: str) -> bool:
    """Delete an organization and cascade delete its members and connections."""
    try:
        _supabase.table("organizations").delete().eq("id", org_id).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.delete_organization.failed", error=str(exc))
        return False


def create_organization_member(payload: dict) -> dict:
    """Add a member to an organization."""
    data = dict(payload)
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    if "created_at" not in data:
        data["created_at"] = now_iso
    data["updated_at"] = now_iso

    try:
        rows = _supabase.table("organization_members").insert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.create_organization_member.failed", error=str(exc))
        return data


def get_organization_member(org_id: str, user_id: str) -> Optional[dict]:
    """Get a member record by org_id and user_id."""
    try:
        return (
            _supabase.table("organization_members")
            .select("*")
            .eq("organization_id", org_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_organization_member.failed", error=str(exc))
        return None


def list_organization_members(org_id: str) -> list[dict]:
    """List all members of an organization."""
    try:
        return (
            _supabase.table("organization_members")
            .select("*")
            .eq("organization_id", org_id)
            .order("created_at", desc=False)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_organization_members.failed", error=str(exc))
        return []


def update_organization_member_role(org_id: str, member_id: str, new_role: str) -> Optional[dict]:
    """Update role of an organization member."""
    try:
        _supabase.table("organization_members").update({
            "role": new_role,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("organization_id", org_id).eq("id", member_id).execute()

        return (
            _supabase.table("organization_members")
            .select("*")
            .eq("id", member_id)
            .maybe_single()
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.update_organization_member_role.failed", error=str(exc))
        return None


def delete_organization_member(org_id: str, member_id: str) -> bool:
    """Remove a member from an organization."""
    try:
        _supabase.table("organization_members").delete().eq("organization_id", org_id).eq("id", member_id).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.delete_organization_member.failed", error=str(exc))
        return False


def get_organization_counts(org_id: str) -> dict[str, int]:
    """Returns member count, aws connection count, and server count for an org."""
    try:
        m_count = len(list_organization_members(org_id))
        c_count = len(list_aws_connections_for_org(org_id))
        s_count = len(list_servers_for_org(org_id))
        return {
            "members_count": m_count,
            "aws_connections_count": c_count,
            "servers_count": s_count,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_organization_counts.failed", error=str(exc))
        return {"members_count": 0, "aws_connections_count": 0, "servers_count": 0}


def create_audit_log_entry(payload: dict) -> dict:
    """Insert an audit log entry."""
    data = dict(payload)
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())
    if "created_at" not in data:
        data["created_at"] = datetime.now(timezone.utc).isoformat()

    try:
        rows = _supabase.table("audit_logs").insert(data).execute().data
        return rows[0] if rows else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.create_audit_log_entry.failed", error=str(exc))
        return data


def list_audit_log_entries(
    org_id: str,
    limit: int = 50,
    offset: int = 0,
    action_filter: Optional[str] = None,
) -> list[dict]:
    """Retrieve audit logs for an organization."""
    try:
        q = _supabase.table("audit_logs").select("*").eq("organization_id", org_id)
        if action_filter:
            q = q.eq("action", action_filter)
        return (
            q.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_audit_log_entries.failed", error=str(exc))
        return []


def list_servers_for_org(org_id: str) -> list[dict]:
    """List servers belonging to an organization."""
    try:
        return (
            _supabase.table("servers")
            .select("*")
            .eq("organization_id", org_id)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_servers_for_org.failed", error=str(exc))
        return []


def list_aws_connections_for_org(org_id: str) -> list[dict]:
    """List AWS connections belonging to an organization."""
    try:
        return (
            _supabase.table("aws_connections")
            .select("*")
            .eq("organization_id", org_id)
            .order("created_at", desc=True)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_aws_connections_for_org.failed", error=str(exc))
        return []


def list_servers_for_connection(connection_id: str) -> list[dict]:
    """List servers associated with a specific AWS connection."""
    try:
        return (
            _supabase.table("servers")
            .select("*")
            .eq("aws_connection_id", connection_id)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_servers_for_connection.failed", error=str(exc))
        return []


def get_telemetry_metrics_count(org_id: str, hours: int = 24) -> int:
    """Calculate total telemetry records ingested for an org in the last N hours."""
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        servers = list_servers_for_org(org_id)
        if not servers:
            return 0
        server_ids = [s["id"] for s in servers]
        res = (
            _supabase.table("server_metrics")
            .select("id", count="exact")
            .in_("server_id", server_ids)
            .gte("recorded_at", since)
            .execute()
        )
        return res.count or len(res.data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_telemetry_metrics_count.failed", error=str(exc))
        return 0




