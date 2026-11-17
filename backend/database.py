"""Supabase (Postgres) database client and query helpers for CloudPulse AI.

The schema lives in ``supabase-schema.sql`` and is applied once in the
Supabase SQL Editor. This module talks to it over PostgREST via the
supabase-py client — there is no local database and no SQLite.

The backend uses the **service-role key**, which bypasses Row Level
Security; RLS (`auth.uid() = owner_id`) protects the tables from direct
anon-key access by the frontend. The service key never leaves the backend.
"""

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

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


def _jwt_role(key: str) -> Optional[str]:
    """Best-effort decode of the ``role`` claim from a Supabase JWT.

    Supabase keys are signed JWTs; we only read the payload to detect a
    misconfigured key (anon vs service_role). No signature verification —
    this is a diagnostic, not an auth decision.
    """
    try:
        import base64
        import json

        payload_b64 = key.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64)).get("role")
    except Exception:  # noqa: BLE001 - legacy/non-JWT keys have no payload
        return None


# Columns the backend reads/writes that only exist after the additive
# migrations have been applied (001 expands telemetry, 004-007 inventory/orgs).
_REQUIRED_SCHEMA_COLUMNS: list[tuple[str, str]] = [
    ("server_metrics", "disk_usage"),
    ("server_metrics", "system_uptime"),
    ("server_metrics", "process_count"),
    ("servers", "source"),
    ("servers", "aws_resource_id"),
    ("servers", "organization_id"),
    ("servers", "aws_connection_id"),
]


def init_db():
    """Verify Supabase connectivity and that the schema has been applied.

    Tables are created by running ``supabase-schema.sql`` in the Supabase SQL
    Editor — DDL cannot be executed over the PostgREST API.

    Beyond connectivity this performs two startup diagnostics so that a
    misconfigured deployment fails loudly instead of silently serving from
    the in-memory cache:
      * key role — an anon key cannot write through RLS (42501) and reads
        return zero rows, so telemetry would never persist;
      * schema completeness — missing migration columns make every extended
        telemetry insert fail (PGRST204/42703).
    """
    try:
        _supabase.table("servers").select("id").limit(1).execute()
    except Exception as exc:
        raise RuntimeError(
            "Could not reach Supabase. Check SUPABASE_URL/SUPABASE_SERVICE_KEY and "
            "that supabase-schema.sql has been applied in the SQL Editor. "
            f"({exc})"
        ) from exc

    role = _jwt_role(SUPABASE_SERVICE_KEY)
    if role and role != "service_role":
        logger.warning(
            "db.key_role.unexpected",
            role=role,
            hint=(
                "SUPABASE_SERVICE_KEY must be the service_role secret "
                "(Supabase Dashboard → Settings → API → service_role). "
                f"A '{role}' key is subject to RLS: reads return empty and "
                "writes fail with 42501, so telemetry cannot persist."
            ),
        )

    missing = []
    for table, col in _REQUIRED_SCHEMA_COLUMNS:
        try:
            _supabase.table(table).select(col).limit(1).execute()
        except Exception:  # noqa: BLE001 - any error means the column is unusable
            missing.append(f"{table}.{col}")
    if missing:
        logger.warning(
            "db.schema.incomplete",
            missing=missing,
            hint=(
                "Apply the additive migrations in migrations/ (001, 006, 007 — "
                "or 001→007 in order for the full schema) in the Supabase SQL "
                "Editor. Extended telemetry and inventory fields cannot "
                "persist until then; inserts will fall back to memory."
            ),
        )

    logger.info("db.connected", provider="supabase")


def db_ping() -> bool:
    """Lightweight connectivity check for /health. Never raises."""
    try:
        _supabase.table("servers").select("id").limit(1).execute()
        return True
    except Exception as exc:  # noqa: BLE001 - health endpoint must not 500
        logger.warning("health.db_ping.failed", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Servers & Telemetry In-Memory High-Speed Cache
# ---------------------------------------------------------------------------

_known_servers: dict[str, dict] = {}
_token_to_server_id: dict[str, str] = {}
_memory_metrics: dict[str, list[dict]] = {}


def sync_known_server(server_data: dict) -> dict:
    """Register or update an active server and its token in the fast cache."""
    if not server_data or not isinstance(server_data, dict):
        return {}
    sid = str(server_data.get("id", ""))
    if not sid:
        return {}
    token = server_data.get("ingestion_token")
    _known_servers[sid] = dict(server_data)
    if token:
        _token_to_server_id[str(token)] = sid
    return _known_servers[sid]


# Columns guaranteed by the base schema — the retry path for upsert_server
# when the live project is still missing additive-migration columns.
_SERVER_BASE_COLUMNS = (
    "id", "server_name", "ip_address", "status", "specifications",
    "owner_id", "ingestion_token", "cost_tag", "created_at",
)


def upsert_server(payload: dict) -> Optional[dict]:
    """Upsert a node into the ``servers`` table (service-role, bypasses RLS).

    Called by POST /api/servers/sync-node so nodes registered over the API
    survive a backend restart. Only supplied columns are written — an upsert
    against a row the frontend provisioned (with owner_id) never touches
    ownership. If the legacy ``servers_status_check`` rejects the caller's
    status (the base vocabulary is active/warning/critical/idle), the row is
    retried with the schema default 'active' — the sync is about registering
    the token, and the anomaly engine manages status from there. Falls back
    to cache-only registration when Supabase still rejects the write.
    """
    data = dict(payload)
    if not data.get("id"):
        return None
    try:
        rows = _supabase.table("servers").upsert(data).execute().data
        if rows:
            return rows[0]
    except Exception as exc:
        logger.warning("db.upsert_server.full_failed", error=str(exc))
        if "status_check" in str(exc) or "23514" in str(exc):
            normalized = dict(data)
            normalized["status"] = "active"
            try:
                rows = _supabase.table("servers").upsert(normalized).execute().data
                if rows:
                    return rows[0]
            except Exception as exc2:
                logger.warning("db.upsert_server.normalized_failed", error=str(exc2))

    # Retry with only the columns guaranteed by the base schema (schema drift
    # on extended columns would otherwise reject the whole upsert).
    base = {k: data[k] for k in _SERVER_BASE_COLUMNS if k in data}
    if base.get("status") not in ("active", "warning", "critical", "idle"):
        base["status"] = "active"
    try:
        rows = _supabase.table("servers").upsert(base).execute().data
        if rows:
            return rows[0]
    except Exception as exc:
        logger.warning("db.upsert_server.base_failed", error=str(exc))
    return None


def list_servers(status_filter: Optional[str] = None) -> list[dict]:
    """Return all servers, optionally filtered by status (excludes terminated nodes by default)."""
    db_servers: list[dict] = []
    try:
        query = _supabase.table("servers").select("*")
        if status_filter:
            query = query.eq("status", status_filter)
        else:
            query = query.neq("status", "terminated")
        res = query.execute().data
        if res:
            db_servers = res
            for s in res:
                sync_known_server(s)
    except Exception as exc:
        logger.warning("db.list_servers.supabase_warning", error=str(exc))

    # Merge with in-memory cached servers
    db_ids = {s["id"] for s in db_servers}
    cached_to_add = [
        s for s in _known_servers.values()
        if s.get("id") not in db_ids and s.get("status") != "terminated"
        and (not status_filter or s.get("status") == status_filter)
    ]
    return db_servers + cached_to_add


def get_server(server_id: str) -> Optional[dict]:
    """Return a single server by id (None when missing)."""
    if not server_id:
        return None
    sid = str(server_id)
    try:
        rows = (
            _supabase.table("servers")
            .select("*")
            .eq("id", sid)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            sync_known_server(rows[0])
            return rows[0]
    except Exception as exc:
        logger.warning("db.get_server.failed", error=str(exc))

    return _known_servers.get(sid)


def get_server_by_token(token: str) -> Optional[dict]:
    """Return the server that owns the given ingestion token (None when unknown)."""
    if not token:
        return None
    token_clean = str(token).strip()

    # 1. Check in-memory fast cache
    if token_clean in _token_to_server_id:
        sid = _token_to_server_id[token_clean]
        if sid in _known_servers:
            return _known_servers[sid]

    # 2. Query Supabase (ingestion_token is UNIQUE — plain select avoids the
    #    PostgREST 406 that .maybe_single() raises on a token miss)
    try:
        rows = (
            _supabase.table("servers")
            .select("*")
            .eq("ingestion_token", token_clean)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            sync_known_server(rows[0])
            return rows[0]
    except Exception as exc:
        logger.warning("db.get_server_by_token.failed", error=str(exc))

    return None


def get_server_by_aws_instance_id(aws_instance_id: str) -> Optional[dict]:
    """Return the server associated with an AWS instance ID (None when missing)."""
    if not aws_instance_id:
        return None
    for s in _known_servers.values():
        if s.get("aws_instance_id") == aws_instance_id:
            return s

    try:
        rows = (
            _supabase.table("servers")
            .select("*")
            .eq("aws_instance_id", aws_instance_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception:
        return None


def get_server_by_aws_resource_id(aws_resource_id: str) -> Optional[dict]:
    """Return the server associated with an AWS resource ID (None when missing)."""
    if not aws_resource_id:
        return None
    for s in _known_servers.values():
        if s.get("aws_resource_id") == aws_resource_id:
            return s
    try:
        rows = (
            _supabase.table("servers")
            .select("*")
            .eq("aws_resource_id", aws_resource_id)
            .limit(1)
            .execute()
            .data
        )
        row = rows[0] if rows else None
        if not row:
            row = get_server_by_aws_instance_id(aws_resource_id)
        return row
    except Exception:
        return None


def upsert_discovered_server(payload: dict) -> dict:
    """Insert or update a discovered AWS server row in the servers table."""
    data = dict(payload)
    if "id" in data:
        server_id = data.pop("id")
        try:
            _supabase.table("servers").update(data).eq("id", server_id).execute()
        except Exception:
            pass
        srv = get_server(server_id) or {}
        if srv:
            sync_known_server(srv)
        return srv
    else:
        if "id" not in data:
            data["id"] = str(uuid.uuid4())
        if "ingestion_token" not in data:
            data["ingestion_token"] = os.urandom(16).hex()
        try:
            rows = _supabase.table("servers").insert(data).execute().data
            if rows:
                sync_known_server(rows[0])
                return rows[0]
        except Exception:
            pass
        sync_known_server(data)
        return data


def update_server_status(server_id: str, status: str) -> dict:
    """Update a server's status field (active, warning, critical, idle, terminating, terminated)."""
    sid = str(server_id)
    if sid in _known_servers:
        _known_servers[sid]["status"] = status
    try:
        _supabase.table("servers").update({"status": status}).eq("id", sid).execute()
    except Exception:
        pass
    return get_server(sid) or {"id": sid, "status": status}


def delete_server(server_id: str, owner_id: Optional[str] = None, org_id: Optional[str] = None) -> bool:
    """Permanently delete a server from the servers table (cascades to metrics, alerts, etc.)."""
    sid = str(server_id)
    _known_servers.pop(sid, None)
    _memory_metrics.pop(sid, None)
    tokens_to_del = [t for t, s in _token_to_server_id.items() if s == sid]
    for t in tokens_to_del:
        _token_to_server_id.pop(t, None)

    try:
        query = _supabase.table("servers").delete().eq("id", sid)
        if owner_id:
            query = query.eq("owner_id", owner_id)
        if org_id:
            query = query.eq("organization_id", org_id)
        query.execute()
        return True
    except Exception as exc:
        logger.warning("db.delete_server.failed", server_id=sid, error=str(exc))
        return True



# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def insert_metric(payload: dict) -> dict:
    """Insert a new server_metrics row into Supabase and in-memory cache.

    Degrades gracefully while the additive migrations are still pending:
      * PGRST204/42703 (column absent from the live schema) — the row is
        retried without the offending extended psutil column so core
        telemetry persists today; full fidelity resumes automatically once
        migrations/008_complete_telemetry_schema.sql has been applied.
      * 23502 (legacy NOT NULL, e.g. estimated_cost_per_hour) — satisfied
        with 0, the honest "no estimate" value (real spend lives in
        daily_costs).
    """
    data = dict(payload)
    if "id" not in data:
        data["id"] = str(uuid.uuid4())
    if "recorded_at" not in data:
        data["recorded_at"] = datetime.now(timezone.utc).isoformat()

    sid = str(data.get("server_id", ""))
    if sid:
        if sid not in _memory_metrics:
            _memory_metrics[sid] = []
        _memory_metrics[sid].append(data)
        if len(_memory_metrics[sid]) > 100:
            _memory_metrics[sid] = _memory_metrics[sid][-100:]

    attempt = dict(data)
    for _ in range(12):  # bounded: one retry per stripped column / not-null fixup
        try:
            rows = _supabase.table("server_metrics").insert(attempt).execute().data
            if rows:
                return rows[0]
            break
        except Exception as exc:
            msg = str(exc)
            # 23502 first — its message also matches the column/relation shape.
            not_null = re.search(r'null value in column "([a-zA-Z_]\w*)"', msg)
            if not_null and attempt.get(not_null.group(1)) is None:
                logger.warning(
                    "db.insert_metric.not_null_defaulted",
                    column=not_null.group(1),
                    value=0,
                )
                attempt[not_null.group(1)] = 0
                continue
            missing = (
                re.search(r"server_metrics\.([a-zA-Z_]\w*)", msg)
                or re.search(r"'([a-zA-Z_]\w*)' column of 'server_metrics'", msg)
                or re.search(r'column "([a-zA-Z_]\w*)" of relation', msg)
            )
            if missing and missing.group(1) in attempt:
                logger.warning(
                    "db.insert_metric.column_missing",
                    column=missing.group(1),
                    hint="Apply migrations/008_complete_telemetry_schema.sql to persist extended telemetry.",
                )
                attempt.pop(missing.group(1), None)
                continue
            logger.warning("db.insert_metric.supabase_warning", error=msg)
            break

    return data


def latest_metrics(server_id: str, limit: int = 10) -> list[dict]:
    """Return the limit most-recent metric rows for a server in chronological order."""
    sid = str(server_id)
    db_rows = []
    try:
        rows = (
            _supabase.table("server_metrics")
            .select("*")
            .eq("server_id", sid)
            .order("recorded_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )
        if rows:
            rows.reverse()
            db_rows = rows
    except Exception:
        pass

    if db_rows:
        return db_rows

    mem_rows = _memory_metrics.get(sid, [])
    return mem_rows[-limit:]


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

def _org_server_ids(org_id: str) -> list[str]:
    """Server ids belonging to an organization (tenant-scope helper)."""
    return [str(s["id"]) for s in list_servers_for_org(org_id) if s.get("id")]


def list_alerts(unresolved_only: bool = True, org_id: Optional[str] = None) -> list[dict]:
    """Return alerts, newest first, with the owning server's name embedded.

    Degrades to an empty feed on transient Supabase errors so a network blip
    can never 500 the dashboard (matches list_servers / latest_metrics).

    When ``org_id`` is given the feed is tenant-scoped to that
    organization's servers (see ``list_alerts_for_servers``).
    """
    if org_id:
        return list_alerts_for_servers(_org_server_ids(org_id), unresolved_only=unresolved_only)
    try:
        query = _supabase.table("system_alerts").select("*, servers(server_name)")
        if unresolved_only:
            query = query.eq("resolved", False)
        rows = query.order("created_at", desc=True).execute().data
    except Exception as exc:
        logger.warning("db.list_alerts.failed", error=str(exc))
        return []

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
    """Write a new system_alerts row (falls back to the payload on DB failure)."""
    if "id" not in payload:
        payload["id"] = str(uuid.uuid4())
    if "created_at" not in payload:
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
    if "resolved" not in payload:
        payload["resolved"] = False

    try:
        rows = _supabase.table("system_alerts").insert(payload).execute().data
        row = rows[0] if rows else payload
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.insert_alert.fallback", error=str(exc))
        row = payload
    row = dict(row)
    row["resolved"] = bool(row["resolved"])
    return row


def resolve_alert(alert_id: str, org_id: Optional[str] = None) -> dict:
    """Mark an alert as resolved. Returns the updated row, or {} when missing.

    When ``org_id`` is given, an alert whose server belongs to another
    organization is treated as missing ({}), so existence is not leaked
    across tenants.
    """
    if org_id:
        existing = get_alert(alert_id)
        if not existing or str(existing.get("server_id")) not in _org_server_ids(org_id):
            return {}
    _supabase.table("system_alerts").update({"resolved": True}).eq("id", alert_id).execute()

    rows = (
        _supabase.table("system_alerts")
        .select("*")
        .eq("id", alert_id)
        .limit(1)
        .execute()
        .data
    )
    row = rows[0] if rows else None
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
    org_id: Optional[str] = None,
) -> list[dict]:
    """Return anomaly events, newest first, with optional filters.

    When ``org_id`` is given the feed is tenant-scoped to that
    organization's servers (see ``list_anomaly_events_for_servers``).
    """
    if org_id:
        return list_anomaly_events_for_servers(
            _org_server_ids(org_id), severity=severity, resolved=resolved, limit=limit
        )
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


def resolve_anomaly_event(event_id: str, org_id: Optional[str] = None) -> dict:
    """Mark an anomaly event as resolved.

    When ``org_id`` is given, an event whose server belongs to another
    organization is treated as missing ({}).
    """
    if org_id:
        existing = get_anomaly_event(event_id)
        if not existing or str(existing.get("server_id")) not in _org_server_ids(org_id):
            return {}
    try:
        _supabase.table("anomaly_events").update({"resolved": True}).eq("id", event_id).execute()
        row = _supabase.table("anomaly_events").select("*").eq("id", event_id).limit(1).execute().data
        return (row[0] if row else None) or {}
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
            existing_rows = (
                _supabase.table("optimization_recommendations")
                .select("id")
                .eq("server_id", server_id)
                .eq("recommendation_type", rec_type)
                .eq("status", "active")
                .limit(1)
                .execute()
                .data
            )
            existing = existing_rows[0] if existing_rows else None
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
    org_id: Optional[str] = None,
) -> list[dict]:
    """Fetch optimization recommendations matching filters.

    When ``org_id`` is given the list is tenant-scoped (organization
    column or per-server ownership — see
    ``list_optimization_recommendations_for_servers``).
    """
    if org_id:
        rows = list_optimization_recommendations_for_servers(
            _org_server_ids(org_id),
            organization_id=org_id,
            service_name=service_name,
            region=region,
            severity=severity,
            recommendation_type=recommendation_type,
            status=status,
            limit=limit,
        )
        if server_id:
            rows = [r for r in rows if str(r.get("server_id")) == str(server_id)]
        formatted_scoped = []
        for r in rows:
            rec = dict(r)
            rec.setdefault("servers", None)
            formatted_scoped.append(rec)
        return formatted_scoped
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


def update_optimization_recommendation_status(
    recommendation_id: str, status: str, org_id: Optional[str] = None
) -> dict:
    """Update recommendation status ('active', 'applied', 'dismissed').

    When ``org_id`` is given, a recommendation owned by another
    organization (by its organization column or its server) is treated
    as missing ({}).
    """
    if org_id:
        existing = get_optimization_recommendation(recommendation_id)
        if not existing:
            return {}
        if str(existing.get("organization_id") or "") != str(org_id) and str(
            existing.get("server_id")
        ) not in _org_server_ids(org_id):
            return {}
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        _supabase.table("optimization_recommendations").update(
            {"status": status, "updated_at": now_iso}
        ).eq("id", recommendation_id).execute()

        rows = (
            _supabase.table("optimization_recommendations")
            .select("*")
            .eq("id", recommendation_id)
            .limit(1)
            .execute()
            .data
        )
        return (rows[0] if rows else None) or {}
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


def list_incidents(
    status_filter: Optional[str] = None, limit: int = 50, org_id: Optional[str] = None
) -> list[dict]:
    """List incidents with embedded server names.

    When ``org_id`` is given the list is tenant-scoped (see
    ``list_incidents_scoped``).
    """
    if org_id:
        return list_incidents_scoped(
            organization_id=org_id,
            server_ids=_org_server_ids(org_id),
            status_filter=status_filter,
            limit=limit,
        )
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
        rows = (
            _supabase.table("incidents")
            .select("*, servers(server_name, specifications, aws_region, aws_instance_id)")
            .eq("id", incident_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            return None
        inc = dict(rows[0])
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
        rows = q.limit(1).execute().data
        return rows[0] if rows else None
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
        rows = (
            _supabase.table("organizations")
            .select("*")
            .eq("id", org_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_organization_by_id.failed", error=str(exc))
        return None


def get_organization_by_slug(slug: str) -> Optional[dict]:
    """Retrieve an organization by slug."""
    try:
        rows = (
            _supabase.table("organizations")
            .select("*")
            .eq("slug", slug)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
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
        rows = (
            _supabase.table("organization_members")
            .select("*")
            .eq("organization_id", org_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
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

        rows = (
            _supabase.table("organization_members")
            .select("*")
            .eq("id", member_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
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


# ---------------------------------------------------------------------------
# Phase 6: Tenant-Scoped Query Helpers (server-side authorization support)
# ---------------------------------------------------------------------------

def list_servers_for_owner(owner_id: str) -> list[dict]:
    """List legacy single-tenant servers owned directly by a user."""
    if not owner_id:
        return []
    try:
        return (
            _supabase.table("servers")
            .select("*")
            .eq("owner_id", str(owner_id))
            .neq("status", "terminated")
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_servers_for_owner.failed", error=str(exc))
        return []


def list_alerts_for_servers(server_ids: list[str], unresolved_only: bool = True) -> list[dict]:
    """Tenant-scoped alert feed: alerts attached to the given servers only."""
    if not server_ids:
        return []
    try:
        query = (
            _supabase.table("system_alerts")
            .select("*, servers(server_name)")
            .in_("server_id", server_ids)
        )
        if unresolved_only:
            query = query.eq("resolved", False)
        rows = query.order("created_at", desc=True).execute().data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_alerts_for_servers.failed", error=str(exc))
        return []

    formatted = []
    for r in rows:
        alert = dict(r)
        embedded = alert.pop("servers", None)
        server_name = embedded.get("server_name") if embedded else None
        alert["servers"] = {"server_name": server_name} if server_name else None
        alert["resolved"] = bool(alert.get("resolved", False))
        formatted.append(alert)
    return formatted


def get_alert(alert_id: str) -> Optional[dict]:
    """Fetch a single alert row by id (None when missing)."""
    if not alert_id:
        return None
    try:
        rows = (
            _supabase.table("system_alerts")
            .select("*")
            .eq("id", str(alert_id))
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_alert.failed", error=str(exc))
        return None


def list_anomaly_events_for_servers(
    server_ids: list[str],
    severity: Optional[str] = None,
    resolved: Optional[bool] = None,
    limit: int = 50,
) -> list[dict]:
    """Tenant-scoped anomaly feed restricted to the given servers."""
    if not server_ids:
        return []
    try:
        query = (
            _supabase.table("anomaly_events")
            .select("*, servers(server_name)")
            .in_("server_id", server_ids)
        )
        if severity:
            query = query.eq("severity", severity)
        if resolved is not None:
            query = query.eq("resolved", resolved)
        rows = query.order("created_at", desc=True).limit(limit).execute().data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_anomaly_events_for_servers.failed", error=str(exc))
        return []

    formatted = []
    for r in rows:
        event = dict(r)
        embedded = event.pop("servers", None)
        server_name = embedded.get("server_name") if embedded else None
        event["servers"] = {"server_name": server_name} if server_name else None
        event["resolved"] = bool(event.get("resolved", False))
        formatted.append(event)
    return formatted


def get_anomaly_event(event_id: str) -> Optional[dict]:
    """Fetch a single anomaly event row by id (None when missing)."""
    if not event_id:
        return None
    try:
        rows = (
            _supabase.table("anomaly_events")
            .select("*")
            .eq("id", str(event_id))
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_anomaly_event.failed", error=str(exc))
        return None


def list_incidents_scoped(
    organization_id: Optional[str] = None,
    server_ids: Optional[list[str]] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Tenant-scoped incident list: org-owned incidents and/or per-server incidents."""
    clauses: list[str] = []
    if organization_id:
        clauses.append(f"organization_id.eq.{organization_id}")
    if server_ids:
        ids = ",".join(str(s) for s in server_ids)
        clauses.append(f"server_id.in.({ids})")
    if not clauses:
        return []

    try:
        query = _supabase.table("incidents").select("*, servers(server_name)").or_(
            ",".join(clauses)
        )
        if status_filter and status_filter != "all":
            query = query.eq("status", status_filter)
        rows = query.order("created_at", desc=True).limit(limit).execute().data

        formatted = []
        for r in rows:
            inc = dict(r)
            embedded = inc.pop("servers", None)
            server_name = embedded.get("server_name") if embedded else None
            inc["servers"] = {"server_name": server_name} if server_name else None
            formatted.append(inc)
        return formatted
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_incidents_scoped.failed", error=str(exc))
        return []


def get_optimization_recommendation(recommendation_id: str) -> Optional[dict]:
    """Fetch a single optimization recommendation by id (None when missing)."""
    if not recommendation_id:
        return None
    try:
        rows = (
            _supabase.table("optimization_recommendations")
            .select("*")
            .eq("id", str(recommendation_id))
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.get_optimization_recommendation.failed", error=str(exc))
        return None


def list_optimization_recommendations_for_servers(
    server_ids: list[str],
    organization_id: Optional[str] = None,
    service_name: Optional[str] = None,
    region: Optional[str] = None,
    severity: Optional[str] = None,
    recommendation_type: Optional[str] = None,
    status: Optional[str] = "active",
    limit: int = 50,
) -> list[dict]:
    """Tenant-scoped recommendation list (org column or per-server ownership)."""
    clauses: list[str] = []
    if organization_id:
        clauses.append(f"organization_id.eq.{organization_id}")
    if server_ids:
        ids = ",".join(str(s) for s in server_ids)
        clauses.append(f"server_id.in.({ids})")
    if not clauses:
        return []

    try:
        query = _supabase.table("optimization_recommendations").select("*").or_(
            ",".join(clauses)
        )
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
        return query.order("estimated_savings_monthly", desc=True).limit(limit).execute().data
    except Exception as exc:  # noqa: BLE001
        logger.warning("db.list_optimization_recommendations_for_servers.failed", error=str(exc))
        return []




