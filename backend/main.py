"""CloudPulse AI — FastAPI backend for infrastructure cost & resource monitoring."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from database import (
    get_daily_costs,
    get_latest_cost_date,
    get_server,
    get_server_by_token,
    init_db,
    insert_alert,
    insert_metric,
    latest_metrics,
    list_alerts,
    list_servers,
    resolve_alert,
    update_server_status,
)
from aws_cost import (
    cloud_configured,
    detect_budget_spikes,
    get_cloud_status,
    sync_daily_costs,
)
from models import (
    AlertResolveResponse,
    CloudStatus,
    MetricPayload,
    MetricResponse,
    ServerOut,
    ServerStatusResponse,
    ServerStatusUpdate,
    SyncResult,
)

load_dotenv()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify Supabase connectivity (schema applied via supabase-schema.sql)
    init_db()
    # Best-effort: pull real costs once at startup when AWS is configured.
    if cloud_configured():
        try:
            result = sync_daily_costs(days_back=14)
            print(f"[CloudPulse] AWS Cost Explorer sync: {result.days_synced} days, "
                  f"{result.matched} cost rows matched, "
                  f"{len(result.unmatched)} unmatched tags.")
        except Exception as exc:  # noqa: BLE001 - startup must not crash on AWS issues
            print(f"[CloudPulse] [WARN] AWS Cost Explorer sync failed at startup: {exc}")
    yield

app = FastAPI(
    title="CloudPulse AI",
    description="Autonomous Cloud Infrastructure Cost & Resource Monitoring API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — only allow explicit frontend origins (comma-separated env var).
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000")
allowed_origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Rate limiting (slowapi; in-memory store, per-process)
# ---------------------------------------------------------------------------
RATE_LIMIT_PER_MINUTE = os.getenv("RATE_LIMIT_PER_MINUTE", "30")

limiter = Limiter(key_func=get_remote_address, default_limits=[])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------------------------
# Thresholds (tunable via env vars in production)
# ---------------------------------------------------------------------------
CPU_HIGH_THRESHOLD = float(os.getenv("CPU_HIGH_THRESHOLD", "85.0"))
IDLE_CPU_THRESHOLD = float(os.getenv("IDLE_CPU_THRESHOLD", "5.0"))
IDLE_RAM_THRESHOLD = float(os.getenv("IDLE_RAM_THRESHOLD", "10.0"))
NETWORK_ANOMALY_THRESHOLD = float(os.getenv("NETWORK_ANOMALY_THRESHOLD", "500.0"))


def _check_thresholds(server_id: str, cpu: float, ram: float, network: float) -> bool:
    """Evaluate metric payload against anomaly thresholds.
    Returns True when at least one alert was written.

    Cost thresholds are intentionally NOT evaluated here — real spend lives in
    daily_costs (AWS Cost Explorer), and BUDGET_SPIKE fires on real daily-cost
    spikes via detect_budget_spikes() during a cloud sync.
    """
    triggered = False
    now = datetime.now(timezone.utc).isoformat()

    # --- HIGH_CPU ---
    if cpu > CPU_HIGH_THRESHOLD:
        insert_alert(
            {
                "server_id": server_id,
                "alert_type": "HIGH_CPU",
                "message": f"CPU spike detected: {cpu:.1f}% (threshold {CPU_HIGH_THRESHOLD}%)",
                "created_at": now,
            }
        )
        # Also escalate server status to critical
        update_server_status(server_id, "critical")
        triggered = True

    # --- IDLE_RESOURCE ---
    if cpu < IDLE_CPU_THRESHOLD and ram < IDLE_RAM_THRESHOLD:
        insert_alert(
            {
                "server_id": server_id,
                "alert_type": "IDLE_RESOURCE",
                "message": (
                    f"Server appears idle — CPU {cpu:.1f}% / RAM {ram:.1f}%. "
                    "Consider downsizing or shutting down."
                ),
                "created_at": now,
            }
        )
        # Flag server as idle
        update_server_status(server_id, "idle")
        triggered = True

    # --- NETWORK_ANOMALY ---
    if network > NETWORK_ANOMALY_THRESHOLD:
        insert_alert(
            {
                "server_id": server_id,
                "alert_type": "NETWORK_ANOMALY",
                "message": (
                    f"Network traffic spike: {network:.2f} MB "
                    f"(threshold {NETWORK_ANOMALY_THRESHOLD} MB) — "
                    "investigate potential DDoS or data exfiltration."
                ),
                "created_at": now,
            }
        )
        update_server_status(server_id, "warning")
        triggered = True

    return triggered


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok"}


def _bearer_token(request: Request) -> Optional[str]:
    """Extract the bearer token from the Authorization header (None if absent)."""
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


@app.post("/api/metrics", response_model=MetricResponse)
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
def ingest_metrics(request: Request, payload: MetricPayload):
    """Accept a telemetry payload, store it, and run anomaly detection.

    Auth: the caller presents a per-server ingestion token as
    ``Authorization: Bearer <token>``. Unknown or missing tokens are rejected —
    servers are no longer auto-registered.
    """
    server = get_server_by_token(_bearer_token(request))
    if not server:
        raise HTTPException(status_code=401, detail="Invalid or missing ingestion token")

    server_id = server["id"]
    row = insert_metric(
        {
            "server_id": server_id,
            "cpu_usage": payload.cpu_usage,
            "ram_usage": payload.ram_usage,
            "network_traffic": payload.network_traffic,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    alert_triggered = _check_thresholds(
        server_id,
        payload.cpu_usage,
        payload.ram_usage,
        payload.network_traffic,
    )

    return MetricResponse(
        id=row.get("id", uuid4()),
        server_id=row.get("server_id", server_id),
        cpu_usage=row.get("cpu_usage", payload.cpu_usage),
        ram_usage=row.get("ram_usage", payload.ram_usage),
        network_traffic=row.get("network_traffic", payload.network_traffic),
        recorded_at=row.get("recorded_at", datetime.now(timezone.utc)),
        alert_triggered=alert_triggered,
    )


@app.get("/api/servers/status", response_model=ServerStatusResponse)
def server_status():
    """Aggregated view of all servers, latest metrics, and unresolved alerts."""
    servers = list_servers()
    active_alerts = list_alerts(unresolved_only=True)

    # Build a summary
    total_nodes = len(servers)
    active_nodes = sum(1 for s in servers if s["status"] == "active")
    warning_nodes = sum(1 for s in servers if s["status"] == "warning")
    critical_nodes = sum(1 for s in servers if s["status"] == "critical")
    idle_nodes = sum(1 for s in servers if s["status"] == "idle")

    # Latest metrics per server (telemetry only — no cost in this channel)
    metrics_map: dict[str, list[dict]] = {}
    latest_metrics_per_server: list[dict] = []
    cpu_sum = 0.0
    cpu_count = 0

    for s in servers:
        sid = s["id"]
        rows = latest_metrics(sid, limit=20)
        metrics_map[sid] = rows
        if rows:
            latest_metrics_per_server.append(
                {
                    "server_id": sid,
                    "server_name": s.get("server_name", sid),
                    "cpu": rows[-1]["cpu_usage"],
                    "ram": rows[-1]["ram_usage"],
                }
            )
            cpu_sum += rows[-1]["cpu_usage"]
            cpu_count += 1

    avg_cpu = round(cpu_sum / cpu_count, 1) if cpu_count else 0.0

    # --- Real spend from AWS Cost Explorer (daily_costs); zeros otherwise ---
    cloud = get_cloud_status()
    costs_map: dict[str, list[dict]] = {}
    monthly_cost_estimate = 0.0
    hourly_cost_estimate = 0.0

    if cloud.cost_source == "aws_cost_explorer":
        daily_rows = get_daily_costs(days=30)
        for row in daily_rows:
            costs_map.setdefault(row["server_id"], []).append(row)
        month_start = datetime.now(timezone.utc).strftime("%Y-%m-01")
        latest_date = max((r["cost_date"] for r in daily_rows), default=None)

        if daily_rows:
            monthly_cost_estimate = sum(
                float(r["amount"]) for r in daily_rows if r["cost_date"] >= month_start
            )
            if latest_date:
                hourly_cost_estimate = (
                    sum(float(r["amount"]) for r in daily_rows if r["cost_date"] == latest_date)
                    / 24.0
                )

    summary = {
        "total_nodes": total_nodes,
        "active_nodes": active_nodes,
        "warning_nodes": warning_nodes,
        "critical_nodes": critical_nodes,
        "idle_nodes": idle_nodes,
        "avg_cpu_load_pct": avg_cpu,
        "monthly_cost_estimate": round(monthly_cost_estimate, 2),
        "hourly_cost_estimate": round(hourly_cost_estimate, 4),
        "active_alerts_count": len(active_alerts),
        "cost_source": cloud.cost_source,
        "cloud_connected": cloud.connected,
        "last_cost_sync": cloud.last_sync,
    }

    return ServerStatusResponse(
        servers=[ServerOut(**s) for s in servers],
        metrics=metrics_map,
        active_alerts=active_alerts,
        summary=summary,
        costs=costs_map,
        cloud=cloud.model_dump(),
    )


@app.get("/api/cloud/status", response_model=CloudStatus)
def cloud_status():
    """Current AWS Cost Explorer integration state."""
    return get_cloud_status()


@app.post("/api/cloud/sync", response_model=SyncResult)
def cloud_sync():
    """Pull real daily costs from AWS Cost Explorer into daily_costs.

    After syncing, raises BUDGET_SPIKE alerts for servers whose latest day
    exceeds 2× their 14-day mean (real spend, not a heuristic).
    """
    if not cloud_configured():
        raise HTTPException(
            status_code=503,
            detail="AWS not configured — set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY "
                   "in backend/.env (see backend/.env.example and the README).",
        )
    result = sync_daily_costs(days_back=14)
    if result.error:
        raise HTTPException(status_code=503, detail=result.error)

    # Real-spend BUDGET_SPIKE detection on the freshly synced daily costs.
    for s in list_servers():
        if detect_budget_spikes(s["id"], days=14):
            insert_alert(
                {
                    "server_id": s["id"],
                    "alert_type": "BUDGET_SPIKE",
                    "message": (
                        f"Daily spend for {s.get('server_name', s['id'])} spiked "
                        "above 2× its 14-day average — review instance sizing."
                    ),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    return result


@app.get("/api/alerts")
def get_all_alerts():
    """Return all alerts, resolved and unresolved."""
    return list_alerts(unresolved_only=False)



@app.get("/api/servers/{server_id}/metrics")
def server_metrics(server_id: str, limit: int = 20):
    """Return historical metrics for a single server."""
    return latest_metrics(server_id, limit=limit)


@app.patch("/api/alerts/{alert_id}/resolve")
def resolve_alert_endpoint(alert_id: str):
    """Mark an alert as resolved."""
    result = resolve_alert(alert_id)
    if not result:
        raise HTTPException(404, detail=f"Alert {alert_id} not found")
    return result


@app.put("/api/servers/{server_id}/status")
def update_server_status_endpoint(server_id: str, body: ServerStatusUpdate):
    """Update a server's operational status."""
    server = get_server(server_id)
    if not server:
        raise HTTPException(404, detail=f"Server {server_id} not found")
    result = update_server_status(server_id, body.status)
    if not result:
        raise HTTPException(500, detail="Failed to update server status")
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
