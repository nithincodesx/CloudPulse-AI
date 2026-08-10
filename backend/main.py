"""CloudPulse AI — FastAPI backend for infrastructure cost & resource monitoring."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from database import (
    get_server,
    init_db,
    insert_alert,
    insert_metric,
    latest_metrics,
    list_alerts,
    list_servers,
    resolve_alert,
    update_server_status,
)
from models import (
    AlertResolveResponse,
    MetricPayload,
    MetricResponse,
    ServerOut,
    ServerStatusResponse,
    ServerStatusUpdate,
)

load_dotenv()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify Supabase connectivity (schema applied via supabase-schema.sql)
    init_db()
    yield

app = FastAPI(
    title="CloudPulse AI",
    description="Autonomous Cloud Infrastructure Cost & Resource Monitoring API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Narrow in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Thresholds (tunable via env vars in production)
# ---------------------------------------------------------------------------
CPU_HIGH_THRESHOLD = float(os.getenv("CPU_HIGH_THRESHOLD", "85.0"))
IDLE_CPU_THRESHOLD = float(os.getenv("IDLE_CPU_THRESHOLD", "5.0"))
IDLE_RAM_THRESHOLD = float(os.getenv("IDLE_RAM_THRESHOLD", "10.0"))
NETWORK_ANOMALY_THRESHOLD = float(os.getenv("NETWORK_ANOMALY_THRESHOLD", "500.0"))


def _check_thresholds(server_id: str, cpu: float, ram: float, cost: float, network: float) -> bool:
    """Evaluate metric payload against anomaly thresholds.
    Returns True when at least one alert was written."""
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

    # --- BUDGET_SPIKE (simple heuristic: cost > 2× estimated baseline) ---
    # In production you'd compare against a rolling window average
    if cost > 2.0:
        insert_alert(
            {
                "server_id": server_id,
                "alert_type": "BUDGET_SPIKE",
                "message": (
                    f"Hourly cost ${cost:.4f} exceeds $2.00 threshold — "
                    "review instance sizing."
                ),
                "created_at": now,
            }
        )
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


@app.post("/api/metrics", response_model=MetricResponse)
def ingest_metrics(payload: MetricPayload):
    """Accept a telemetry payload, store it, and run anomaly detection."""
    server = get_server(payload.server_id)
    if not server:
        # Auto-register unknown servers instead of failing 404
        from database import upsert_server
        upsert_server({
            "id": payload.server_id,
            "server_name": f"host-{payload.server_id[:8]}",
            "status": "active",
        })

    row = insert_metric(
        {
            "server_id": payload.server_id,
            "cpu_usage": payload.cpu_usage,
            "ram_usage": payload.ram_usage,
            "network_traffic": payload.network_traffic,
            "estimated_cost_per_hour": payload.estimated_cost_per_hour,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    alert_triggered = _check_thresholds(
        payload.server_id,
        payload.cpu_usage,
        payload.ram_usage,
        payload.estimated_cost_per_hour,
        payload.network_traffic,
    )

    return MetricResponse(
        id=row.get("id", uuid4()),
        server_id=row.get("server_id", payload.server_id),
        cpu_usage=row.get("cpu_usage", payload.cpu_usage),
        ram_usage=row.get("ram_usage", payload.ram_usage),
        network_traffic=row.get("network_traffic", payload.network_traffic),
        estimated_cost_per_hour=row.get("estimated_cost_per_hour", payload.estimated_cost_per_hour),
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

    # Latest metrics per server
    metrics_map: dict[str, list[dict]] = {}
    latest_metrics_per_server: list[dict] = []
    total_cost_hourly = 0.0
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
            total_cost_hourly += rows[-1]["estimated_cost_per_hour"]
            cpu_sum += rows[-1]["cpu_usage"]
            cpu_count += 1

    avg_cpu = round(cpu_sum / cpu_count, 1) if cpu_count else 0.0
    monthly_cost_estimate = round(total_cost_hourly * 730, 2)  # ~730 hrs/month

    summary = {
        "total_nodes": total_nodes,
        "active_nodes": active_nodes,
        "warning_nodes": warning_nodes,
        "critical_nodes": critical_nodes,
        "idle_nodes": idle_nodes,
        "avg_cpu_load_pct": avg_cpu,
        "monthly_cost_estimate": monthly_cost_estimate,
        "hourly_cost_estimate": round(total_cost_hourly, 4),
        "active_alerts_count": len(active_alerts),
    }

    return ServerStatusResponse(
        servers=[ServerOut(**s) for s in servers],
        metrics=metrics_map,
        active_alerts=active_alerts,
        summary=summary,
    )


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
