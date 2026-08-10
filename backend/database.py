"""Supabase (Postgres) database client and query helpers for CloudPulse AI.

The schema lives in ``supabase-schema.sql`` and is applied once in the
Supabase SQL Editor. This module talks to it over PostgREST via the
supabase-py client — there is no local database and no SQLite.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_KEY must be set. Copy backend/.env.example "
        "to backend/.env and fill them in, then apply supabase-schema.sql in "
        "the Supabase SQL Editor."
    )

try:
    _supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as exc:
    raise RuntimeError(
        "Could not initialize the Supabase client from SUPABASE_URL/SUPABASE_KEY. "
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
        print("[CloudPulse] Supabase connected — schema OK.")
    except Exception as exc:
        raise RuntimeError(
            "Could not reach Supabase. Check SUPABASE_URL/SUPABASE_KEY and "
            "that supabase-schema.sql has been applied in the SQL Editor. "
            f"({exc})"
        ) from exc


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


def upsert_server(payload: dict) -> dict:
    """Register or update a server node."""
    if "id" not in payload:
        payload["id"] = str(uuid.uuid4())
    if "created_at" not in payload:
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
    if "status" not in payload:
        payload["status"] = "active"

    fields = {
        "server_name": payload.get("server_name", "Unknown Node"),
        "ip_address": payload.get("ip_address"),
        "status": payload["status"],
        "specifications": payload.get("specifications"),
    }

    if get_server(payload["id"]) is not None:
        _supabase.table("servers").update(fields).eq("id", payload["id"]).execute()
    else:
        _supabase.table("servers").insert(
            {**fields, "id": payload["id"], "created_at": payload["created_at"]}
        ).execute()
    return get_server(payload["id"])


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
