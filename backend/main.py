"""CloudPulse AI — FastAPI backend for infrastructure cost & resource monitoring."""

import os
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from database import (
    create_aws_connection,
    create_or_update_incident,
    db_ping,
    delete_alert_rule,
    delete_organization,
    delete_server,
    delete_aws_connection,
    delete_notification_channel,
    get_aws_connection,
    get_daily_costs,
    get_incident,
    get_latest_cost_date,
    get_organization_by_id,
    get_organization_counts,
    get_server,
    get_organization_member,
    get_server_by_token,
    init_db,
    insert_alert,
    insert_anomaly_event,
    insert_incident_note,
    insert_incident_timeline_event,
    insert_metric,
    insert_notification_log,
    latest_metrics,
    sync_known_server,
    upsert_server,
    list_alert_rules,
    list_alerts,
    list_alerts_for_servers,
    list_anomaly_events,
    list_aws_connections,
    list_aws_connections_for_org,
    list_incident_notes,
    list_incident_timeline,
    list_incidents,
    list_notification_channels,
    list_notification_logs,
    list_optimization_recommendations,
    list_organization_members,
    list_organizations_for_user,
    list_servers,
    list_servers_for_org,
    resolve_alert,
    resolve_anomaly_event,
    rpc_baseline,
    update_aws_connection,
    update_incident_status,
    update_organization,
    update_optimization_recommendation_status,
    update_server_status,
    upsert_alert_rule,
    upsert_notification_channel,
    upsert_optimization_recommendations,
)
from auth import (
    AuthenticatedUser,
    AuthenticationError,
    AuthorizationError,
    authorize_connection,
    authorize_server,
    get_current_user,
    resolve_org_for_user,
)
from aws_credentials import (
    diagnose_connection_health,
    generate_cloudformation_quick_launch_url,
    generate_external_id,
    generate_iam_permissions_policy,
    generate_iam_trust_policy,
    get_cloudpulse_account_id,
    validate_role_arn,
)
from aws_service import (
    verify_and_save_connection,
    verify_connection_credentials,
)
from aws_cost import (
    cloud_configured,
    detect_budget_spikes,
    detect_cost_anomalies,
    fetch_account_breakdown,
    fetch_region_breakdown,
    fetch_service_breakdown,
    get_cloud_status,
    get_cost_trends,
    sync_daily_costs,
)
from aws_discovery import discovery_configured, sync_aws_resources
from anomaly import (
    BASELINE_DAYS,
    baseline_from_rpc,
    check_advanced_anomalies,
    check_anomalies,
    compute_rolling_baseline,
    compute_time_aware_baseline,
    most_severe,
)
from cost_optimizer import (
    analyze_server_utilization,
    run_fleet_optimization_analysis,
)
from insights import generate_weekly_summary, get_latest_summary, run_weekly_job
from ai_investigation import (
    build_incident_facts,
    generate_fallback_investigation,
    run_ai_incident_investigation,
)
from alert_rules import (
    evaluate_metric_against_rules,
    evaluate_optimization_rules,
)
from notifications import (
    dispatch_alert_notifications,
    send_discord_webhook,
    send_email_alert,
    send_generic_webhook,
    send_slack_webhook,
)
from incidents import (
    create_incident_record,
    create_timeline_entry,
    validate_status_transition,
)
from models import (
    AIInvestigationOut,
    AlertResolveResponse,
    AlertRuleCreate,
    AlertRuleOut,
    AnomalyEventOut,
    AuditLogOut,
    AWSConnectionCreate,
    AWSConnectionInitiateRequest,
    AWSConnectionInitiateResponse,
    AWSConnectionOut,
    AWSConnectionUpdate,
    AWSConnectionVerifyResponse,
    AWSHealthDiagnosticResponse,
    CloudStatus,
    DiscoveryResult,
    IncidentCreate,
    IncidentNoteCreate,
    IncidentNoteOut,
    IncidentOut,
    IncidentStatusUpdate,
    IncidentTimelineOut,
    InsightGenerateResult,
    InsightOut,
    MetricPayload,
    MetricResponse,
    NotificationChannelCreate,
    NotificationChannelOut,
    NotificationLogOut,
    OptimizationAnalyzeResult,
    OptimizationRecommendationOut,
    OptimizationSummaryOut,
    OrganizationCreate,
    OrganizationMemberInvite,
    OrganizationMemberOut,
    OrganizationMemberUpdateRole,
    OrganizationOut,
    OrganizationUpdate,
    OrganizationUsageOut,
    RecommendationStatusUpdate,
    ServerOut,
    ServerStatusResponse,
    ServerStatusUpdate,
    ServerTerminateResponse,
    SyncEngineResult,
    SyncResult,
)
from tenant_service import (
    change_member_role,
    get_or_create_default_workspace,
    invite_member_to_org,
    provision_organization,
    remove_member_from_org,
    verify_permission,
)
from audit_service import AuditActions, get_audit_trail, log_audit_event
from billing_service import calculate_organization_usage
from sync_engine import run_centralized_sync

load_dotenv()

from logging_conf import configure_logging, get_logger

# Structured logging (JSON in prod, colored console in dev).
configure_logging()
logger = get_logger("backend.main")

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify Supabase connectivity (schema applied via supabase-schema.sql)
    init_db()
    # Best-effort: pull real costs once at startup when AWS is configured.
    if cloud_configured():
        try:
            result = sync_daily_costs(days_back=14)
            logger.info(
                "aws.cost.sync",
                days_synced=result.days_synced,
                matched=result.matched,
                unmatched=len(result.unmatched),
            )
        except Exception as exc:  # noqa: BLE001 - startup must not crash on AWS issues
            logger.warning("aws.cost.sync_failed_at_startup", error=str(exc))

    # Best-effort: discover AWS EC2 instances once at startup when AWS is configured.
    if discovery_configured():
        try:
            disc_res = sync_aws_resources()
            logger.info(
                "aws.discovery.startup",
                discovered=disc_res.discovered_count,
                created=disc_res.created_count,
                updated=disc_res.updated_count,
                region=disc_res.region,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("aws.discovery.failed_at_startup", error=str(exc))

    # Background Scheduler (Weekly AI summary & Periodic AWS discovery).
    from apscheduler.schedulers.background import BackgroundScheduler  # noqa: PLC0415

    insight_dow = os.getenv("WEEKLY_INSIGHT_DOW", "mon")
    insight_hour = int(os.getenv("WEEKLY_INSIGHT_HOUR", "9"))
    insight_minute = int(os.getenv("WEEKLY_INSIGHT_MINUTE", "0"))
    insight_tz = os.getenv("WEEKLY_INSIGHT_TZ", "UTC")

    scheduler = BackgroundScheduler(timezone=insight_tz)
    scheduler.add_job(
        run_weekly_job,
        "cron",
        day_of_week=insight_dow,
        hour=insight_hour,
        minute=insight_minute,
        id="weekly_ai_summary",
        replace_existing=True,
    )

    discovery_interval = int(os.getenv("AWS_DISCOVERY_INTERVAL_MINUTES", "30"))
    if discovery_configured() and discovery_interval > 0:
        scheduler.add_job(
            sync_aws_resources,
            "interval",
            minutes=discovery_interval,
            id="aws_resource_discovery",
            replace_existing=True,
        )
        logger.info("aws.discovery.scheduled", interval_minutes=discovery_interval)

    scheduler.start()
    logger.info(
        "weekly_summary.scheduled",
        day=insight_dow,
        hour=insight_hour,
        minute=insight_minute,
        tz=insight_tz,
    )

    yield

    scheduler.shutdown(wait=False)

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
# Anomaly detection
# ---------------------------------------------------------------------------
# Static thresholds were replaced by a rolling baseline: per server, per metric,
# a 7-day mean/stddev is aggregated in Postgres (metrics_baseline RPC) and the
# latest sample is flagged by z-score (see backend/anomaly.py). This is
# statistics, not ML. BUDGET_SPIKE still fires on real daily-cost spikes via
# detect_budget_spikes() during a cloud sync.


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Liveness + DB connectivity. Used by Render's health check and CI."""
    if db_ping():
        return {"status": "ok", "database": "connected"}
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "database": "error", "detail": "Supabase unreachable"},
    )


def _bearer_token(request: Request) -> Optional[str]:
    """Extract the bearer token from the Authorization header (None if absent)."""
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


@app.post("/api/metrics", response_model=MetricResponse)
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
def ingest_metrics(request: Request, payload: MetricPayload = Body(...)):
    """Accept a telemetry payload, store it, and run anomaly detection.

    Auth: the caller presents a per-server ingestion token as
    ``Authorization: Bearer <token>``. Unknown or missing tokens are rejected —
    servers are no longer auto-registered.
    """
    server = get_server_by_token(_bearer_token(request))
    if not server:
        raise HTTPException(status_code=401, detail="Invalid or missing ingestion token")

    server_id = server["id"]
    metric_data = {
        "server_id": server_id,
        "cpu_usage": payload.cpu_usage,
        "ram_usage": payload.ram_usage,
        "network_traffic": payload.network_traffic,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload.disk_usage is not None:
        metric_data["disk_usage"] = payload.disk_usage
    if payload.disk_io is not None:
        metric_data["disk_io"] = payload.disk_io
    if payload.system_uptime is not None:
        metric_data["system_uptime"] = payload.system_uptime
    if payload.load_average is not None:
        metric_data["load_average"] = payload.load_average
    if payload.process_count is not None:
        metric_data["process_count"] = payload.process_count
    if payload.network_stats is not None:
        metric_data["network_stats"] = payload.network_stats

    row = insert_metric(metric_data)

    # If the server was awaiting telemetry (pending), transition to active
    if server.get("status") == "pending":
        update_server_status(server_id, "active")

    # Advanced statistical anomaly detection with time-aware and rolling baselines.
    # We pass recent metrics history to enable hour-of-day/day-of-week comparisons.
    recent_history = latest_metrics(server_id, limit=30)
    rpc_dict = baseline_from_rpc(rpc_baseline(server_id, BASELINE_DAYS))
    anomalies = check_advanced_anomalies(
        server_id=server_id,
        cpu=payload.cpu_usage,
        ram=payload.ram_usage,
        network=payload.network_traffic,
        disk_usage=payload.disk_usage,
        metrics_history=recent_history,
        rpc_baseline_dict=rpc_dict,
    )

    for anomaly in anomalies:
        # Record into the anomaly_events table (Phase 2 structured schema)
        insert_anomaly_event(
            {
                "server_id": server_id,
                "metric_name": anomaly.get("metric_name", "system"),
                "current_value": anomaly.get("current_value", payload.cpu_usage),
                "baseline_value": anomaly.get("baseline_value", 0.0),
                "deviation_sigma": anomaly.get("deviation_sigma"),
                "severity": anomaly.get("severity", "warning"),
                "consecutive_count": anomaly.get("consecutive_count", 1),
                "duration_seconds": anomaly.get("duration_seconds", 0),
                "detection_method": anomaly.get("detection_method", "rolling_zscore"),
                "explanation": anomaly.get("message", ""),
                "meta": anomaly.get("meta", {}),
                "resolved": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        # Also persist to system_alerts for legacy backwards compatibility
        insert_alert(
            {
                "server_id": server_id,
                "alert_type": anomaly["alert_type"],
                "message": anomaly["message"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    if anomalies:
        # Apply the most severe status only (critical > warning > info/idle).
        update_server_status(server_id, most_severe([a["status"] for a in anomalies]))
    alert_triggered = bool(anomalies)

    # Phase 3: Evaluate customizable alert rules & dispatch notifications
    try:
        active_rules = list_alert_rules()
        if active_rules:
            active_channels = list_notification_channels()
            triggered_rules = evaluate_metric_against_rules(
                rules=active_rules,
                server=server,
                metric_payload=metric_data,
                anomaly_events=anomalies,
            )
            for tr in triggered_rules:
                # 1. Create incident record
                inc_rec = create_incident_record(
                    server_id=server_id,
                    title=tr["notification_payload"]["title"],
                    description=tr["notification_payload"]["message"],
                    incident_type=tr["rule_type"],
                    severity=tr["severity"],
                )
                saved_inc = create_or_update_incident(inc_rec)
                inc_id = saved_inc.get("id", inc_rec["id"])

                # 2. Timeline entry for detection
                insert_incident_timeline_event(
                    create_timeline_entry(
                        incident_id=inc_id,
                        event_type="DETECTION",
                        message=tr["notification_payload"]["message"],
                        actor="AlertRuleEngine",
                        meta=tr["notification_payload"].get("meta", {}),
                    )
                )

                # 3. Match relevant channels
                target_types = set(tr.get("target_channels", ["webhook"]))
                relevant_channels = [
                    ch for ch in active_channels
                    if ch.get("channel_type") in target_types or "webhook" in target_types
                ]

                # 4. Dispatch notifications
                delivery_results = dispatch_alert_notifications(
                    payload=tr["notification_payload"],
                    channels=relevant_channels,
                    cooldown_minutes=tr.get("cooldown_minutes", 15),
                )

                # 5. Log delivery outcomes
                for dr in delivery_results:
                    insert_notification_log({
                        "rule_id": tr.get("rule_id"),
                        "incident_id": inc_id,
                        "server_id": server_id,
                        "channel_type": dr["channel_type"],
                        "severity": tr["severity"],
                        "recipient_target": dr["recipient_target"],
                        "status": dr["status"],
                        "payload": tr["notification_payload"],
                        "error_message": dr.get("error_message"),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                    if dr["status"] == "sent":
                        insert_incident_timeline_event(
                            create_timeline_entry(
                                incident_id=inc_id,
                                event_type="NOTIFICATION_SENT",
                                message=f"Notification dispatched to {dr['channel_type']} ({dr['recipient_target']}).",
                                actor="NotificationPipeline",
                            )
                        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics.alert_dispatch_failed", error=str(exc))

    return MetricResponse(
        id=row.get("id", uuid4()),
        server_id=row.get("server_id", server_id),
        cpu_usage=row.get("cpu_usage", payload.cpu_usage),
        ram_usage=row.get("ram_usage", payload.ram_usage),
        network_traffic=row.get("network_traffic", payload.network_traffic),
        disk_usage=row.get("disk_usage", payload.disk_usage),
        disk_io=row.get("disk_io", payload.disk_io),
        system_uptime=row.get("system_uptime", payload.system_uptime),
        load_average=row.get("load_average", payload.load_average),
        process_count=row.get("process_count", payload.process_count),
        network_stats=row.get("network_stats", payload.network_stats),
        recorded_at=row.get("recorded_at", datetime.now(timezone.utc)),
        alert_triggered=alert_triggered,
    )


@app.post("/api/servers/sync-node")
def sync_node_endpoint(
    payload: dict = Body(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Register or sync a node's metadata and ingestion token into the backend.

    The node is also upserted into Supabase (service-role key, RLS bypassed)
    so the registry and its ingestion tokens survive a backend restart. The
    upsert only writes the columns it was given: it never overwrites the
    owner_id the frontend set at provision time.
    """
    if not payload.get("id"):
        raise HTTPException(400, detail="Node ID is required")
    upsert_server(payload)
    synced = sync_known_server(payload)
    return {"status": "synced", "server": synced}


@app.get("/api/servers/status", response_model=ServerStatusResponse)
def server_status(user: AuthenticatedUser = Depends(get_current_user)):
    """Aggregated view of the caller's workspace: servers, metrics, alerts.

    Tenant-scoped — only the authenticated user's organization is ever
    returned (auto-provisions the default workspace on first run).
    """
    org_id, _role = resolve_org_for_user(
        user, None, permission="view_resources", auto_provision=True
    )
    servers = list_servers_for_org(org_id)
    active_alerts = list_alerts_for_servers(
        [str(s["id"]) for s in servers], unresolved_only=True
    )

    # Build a summary
    total_nodes = len(servers)
    active_nodes = sum(1 for s in servers if s["status"] == "active")
    warning_nodes = sum(1 for s in servers if s["status"] == "warning")
    critical_nodes = sum(1 for s in servers if s["status"] == "critical")
    idle_nodes = sum(1 for s in servers if s["status"] == "idle")

    aws_discovered_nodes = sum(1 for s in servers if s.get("source") == "aws_discovery")
    agent_nodes = sum(1 for s in servers if s.get("source") != "aws_discovery")

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
        # Per-server loop: get_daily_costs(server_id=None, days=N) would apply
        # PostgREST's .limit(N) across ALL servers, truncating multi-node fleets.
        daily_rows: list[dict] = []
        for s in servers:
            daily_rows += get_daily_costs(server_id=s["id"], days=30)
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
        "aws_discovered_nodes": aws_discovered_nodes,
        "agent_nodes": agent_nodes,
        "avg_cpu_load_pct": avg_cpu,
        "monthly_cost_estimate": round(monthly_cost_estimate, 2),
        "hourly_cost_estimate": round(hourly_cost_estimate, 4),
        "active_alerts_count": len(active_alerts),
        "cost_source": cloud.cost_source,
        "cloud_connected": cloud.connected,
        "last_cost_sync": cloud.last_sync,
    }

    discovery_summary = {
        "configured": discovery_configured(),
        "discovered_nodes": aws_discovered_nodes,
    }

    return ServerStatusResponse(
        servers=[ServerOut(**s) for s in servers],
        metrics=metrics_map,
        active_alerts=active_alerts,
        summary=summary,
        costs=costs_map,
        cloud=cloud.model_dump(),
        discovery=discovery_summary,
    )


@app.get("/api/cloud/status", response_model=CloudStatus)
def cloud_status(
    connection_id: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Current AWS Cost Explorer integration state (tenant connection or default)."""
    conn = get_aws_connection(connection_id) if connection_id else None
    if not conn:
        conns = list_aws_connections()
        connected_conn = next((c for c in conns if c.get("status") == "connected"), None)
        conn = connected_conn or (conns[0] if conns else None)
    return get_cloud_status(connection=conn)


@app.post("/api/cloud/discover", response_model=DiscoveryResult)
def cloud_discover(
    region: Optional[str] = None,
    connection_id: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Trigger AWS EC2 resource discovery to automatically discover and sync instances."""
    conn = get_aws_connection(connection_id) if connection_id else None
    if not conn:
        conns = list_aws_connections()
        conn = next((c for c in conns if c.get("status") == "connected"), None)

    if not discovery_configured(conn):
        raise HTTPException(
            status_code=503,
            detail="AWS not configured — connect an AWS account in the dashboard.",
        )
    result = sync_aws_resources(region=region, connection=conn)
    if result.error:
        raise HTTPException(status_code=503, detail=result.error)
    return result


@app.post("/api/cloud/sync", response_model=SyncResult)
def cloud_sync(
    connection_id: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Pull real daily costs from AWS Cost Explorer into daily_costs."""
    conn = get_aws_connection(connection_id) if connection_id else None
    if not conn:
        conns = list_aws_connections()
        conn = next((c for c in conns if c.get("status") == "connected"), None)

    if not cloud_configured(conn):
        raise HTTPException(
            status_code=503,
            detail="AWS not configured — connect an AWS account in the dashboard.",
        )
    result = sync_daily_costs(days_back=14, connection=conn)
    if result.error:
        raise HTTPException(status_code=503, detail=result.error)

    # Real-spend BUDGET_SPIKE detection on the freshly synced daily costs.
    # Scoped to the caller's workspace so a sync never writes alerts for
    # another tenant's servers.
    _sync_org_id, _ = resolve_org_for_user(
        user, None, permission="view_costs", auto_provision=True
    )
    for s in list_servers_for_org(_sync_org_id):
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


# ---------------------------------------------------------------------------
# Phase 4: Multi-Tenant SaaS AWS Connection Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/aws/connections/initiate", response_model=AWSConnectionInitiateResponse)
def initiate_aws_connection(
    payload: AWSConnectionInitiateRequest = Body(default=AWSConnectionInitiateRequest()),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Generate cryptographically secure ExternalId, Trust Policy, and CloudFormation Quick Launch URL."""
    ext_id = generate_external_id()
    cloudpulse_acc = get_cloudpulse_account_id()
    trust_policy = generate_iam_trust_policy(ext_id, cloudpulse_acc)
    perms_policy = generate_iam_permissions_policy()
    cf_url = generate_cloudformation_quick_launch_url(ext_id, region=payload.region, cloudpulse_account_id=cloudpulse_acc)

    return AWSConnectionInitiateResponse(
        external_id=ext_id,
        cloudpulse_account_id=cloudpulse_acc,
        trust_policy=trust_policy,
        permissions_policy=perms_policy,
        cloudformation_quick_create_url=cf_url,
        region=payload.region,
    )


@app.get("/api/aws/connections", response_model=list[AWSConnectionOut])
def list_aws_connections_endpoint(user: AuthenticatedUser = Depends(get_current_user)):
    """List AWS connections for the authenticated user's organization."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_aws_connections")
    return list_aws_connections_for_org(org_id)


@app.post("/api/aws/connections", response_model=AWSConnectionOut)
def create_aws_connection_endpoint(
    payload: AWSConnectionCreate = Body(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Save newly created AWS cross-account connection and attempt immediate verification."""
    org_id, _role = resolve_org_for_user(user, None, permission="connect_aws")
    role_arn = payload.role_arn.strip()
    if not validate_role_arn(role_arn):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Role ARN format: '{role_arn}'. Expected format: arn:aws:iam::123456789012:role/RoleName",
        )

    conn_data = {
        "user_id": user.user_id,
        "organization_id": org_id,
        "role_arn": role_arn,
        "external_id": payload.external_id,
        "region": payload.region,
        "display_name": payload.display_name,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload.aws_account_id:
        conn_data["aws_account_id"] = payload.aws_account_id

    created = create_aws_connection(conn_data)
    conn_id = str(created.get("id"))

    # Auto-verify connection
    try:
        verified = verify_and_save_connection(conn_id, user_id=user.user_id)
        return verified
    except Exception:  # noqa: BLE001
        return created


@app.get("/api/aws/connections/{connection_id}", response_model=AWSConnectionOut)
def get_aws_connection_endpoint(
    connection_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get single AWS connection details. Authorized via JWT + org membership."""
    conn = authorize_connection(user, connection_id, permission="view_aws_connections")
    return conn


@app.post("/api/aws/connections/{connection_id}/verify", response_model=AWSConnectionVerifyResponse)
def verify_aws_connection_endpoint(
    connection_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Verify an AWS connection by assuming the role and testing permissions."""
    authorize_connection(user, connection_id, permission="view_aws_connections")
    try:
        verified = verify_and_save_connection(connection_id, user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    is_success = verified.get("status") == "connected"
    return AWSConnectionVerifyResponse(
        success=is_success,
        status=verified.get("status", "error"),
        aws_account_id=verified.get("aws_account_id"),
        error_message=verified.get("error_message"),
        connection=verified,
    )


@app.get("/api/aws/connections/{connection_id}/health", response_model=AWSHealthDiagnosticResponse)
def get_aws_connection_health_endpoint(
    connection_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Run comprehensive granular health checks on an AWS connection."""
    conn = authorize_connection(user, connection_id, permission="view_aws_connections")
    diag = diagnose_connection_health(conn)
    update_aws_connection(connection_id, {
        "health_status": diag["health_status"],
        "health_checks": diag["checks"],
    })

    return AWSHealthDiagnosticResponse(
        connection_id=connection_id,
        health_status=diag["health_status"],
        checks=diag["checks"],
        diagnosed_at=datetime.now(timezone.utc).isoformat(),
        summary=diag["summary"],
    )


@app.post("/api/aws/connections/{connection_id}/sync")
def sync_aws_connection_endpoint(
    connection_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Run centralized idempotent AWS sync pipeline."""
    conn = authorize_connection(user, connection_id, permission="sync_aws")
    try:
        result = run_centralized_sync(
            connection_id=connection_id,
            organization_id=conn.get("organization_id"),
            actor_id=user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@app.delete("/api/aws/connections/{connection_id}")
def delete_aws_connection_endpoint(
    connection_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Disconnect and remove an AWS connection."""
    conn = authorize_connection(user, connection_id, permission="connect_aws")
    deleted = delete_aws_connection(connection_id, user_id=user.user_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete AWS connection")

    if conn.get("organization_id"):
        log_audit_event(
            organization_id=conn["organization_id"],
            action=AuditActions.AWS_DISCONNECTED,
            resource_type="AWS_CONNECTION",
            actor_id=user.user_id,
            resource_id=connection_id,
            metadata={"display_name": conn.get("display_name"), "role_arn": conn.get("role_arn")},
        )

    return {"status": "deleted", "connection_id": connection_id}


# ---------------------------------------------------------------------------
# Phase 5: Organizations & Tenant Workspace Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/organizations", response_model=list[OrganizationOut])
def list_organizations_endpoint(user: AuthenticatedUser = Depends(get_current_user)):
    """List all organizations/workspaces for the authenticated user, auto-provisioning default if none."""
    default_org = get_or_create_default_workspace(user.user_id, user_email=user.email)
    orgs = list_organizations_for_user(user.user_id)
    if not orgs and default_org:
        orgs = [default_org]

    # Populate resource counts
    for o in orgs:
        counts = get_organization_counts(o["id"])
        o["members_count"] = counts["members_count"]
        o["aws_connections_count"] = counts["aws_connections_count"]
        o["servers_count"] = counts["servers_count"]

    return orgs


@app.post("/api/organizations", response_model=OrganizationOut)
def create_organization_endpoint(
    payload: OrganizationCreate,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Create a new organization workspace and assign the creator as OWNER."""
    org = provision_organization(
        name=payload.name,
        user_id=user.user_id,
        user_email=user.email,
        plan_tier=payload.plan_tier,
    )
    counts = get_organization_counts(org["id"])
    org["members_count"] = counts["members_count"]
    org["aws_connections_count"] = counts["aws_connections_count"]
    org["servers_count"] = counts["servers_count"]
    return org


@app.get("/api/organizations/{org_id}", response_model=OrganizationOut)
def get_organization_endpoint(
    org_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get single organization details. Authorized via JWT + org membership."""
    resolved_org_id, role = resolve_org_for_user(user, org_id, permission="view_org")
    org = get_organization_by_id(resolved_org_id)
    if not org:
        raise HTTPException(status_code=404, detail=f"Organization {org_id} not found")
    counts = get_organization_counts(org_id)
    org["user_role"] = role
    org["members_count"] = counts["members_count"]
    org["aws_connections_count"] = counts["aws_connections_count"]
    org["servers_count"] = counts["servers_count"]
    return org


@app.put("/api/organizations/{org_id}", response_model=OrganizationOut)
def update_organization_endpoint(
    org_id: str,
    payload: OrganizationUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Update organization settings (OWNER only)."""
    resolve_org_for_user(user, org_id, permission="manage_org_settings")

    updates = {k: v for k, v in payload.dict().items() if v is not None}
    updated = update_organization(org_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Organization {org_id} not found")

    log_audit_event(
        organization_id=org_id,
        action=AuditActions.SETTINGS_UPDATED,
        resource_type="ORGANIZATION",
        actor_id=user.user_id,
        resource_id=org_id,
        metadata=updates,
    )

    return updated


@app.delete("/api/organizations/{org_id}")
def delete_organization_endpoint(
    org_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Delete organization workspace (OWNER only)."""
    resolve_org_for_user(user, org_id, permission="delete_org")

    ok = delete_organization(org_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete organization")
    return {"status": "deleted", "organization_id": org_id}


# ---------------------------------------------------------------------------
# Phase 5: Member Management & RBAC Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/organizations/{org_id}/members", response_model=list[OrganizationMemberOut])
def list_org_members_endpoint(
    org_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List all members of an organization."""
    resolve_org_for_user(user, org_id, permission="view_members")
    return list_organization_members(org_id)


@app.post("/api/organizations/{org_id}/members", response_model=OrganizationMemberOut)
def invite_org_member_endpoint(
    org_id: str,
    payload: OrganizationMemberInvite,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Invite a new member to the organization (OWNER or ADMIN)."""
    resolve_org_for_user(user, org_id, permission="manage_members")
    try:
        invited = invite_member_to_org(
            organization_id=org_id,
            email=payload.email,
            role=payload.role,
            inviter_id=user.user_id,
            inviter_email=user.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return invited


@app.put("/api/organizations/{org_id}/members/{member_id}", response_model=OrganizationMemberOut)
def update_org_member_role_endpoint(
    org_id: str,
    member_id: str,
    payload: OrganizationMemberUpdateRole,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Update a member's role (OWNER only)."""
    resolve_org_for_user(user, org_id, permission="manage_members")
    try:
        updated = change_member_role(
            organization_id=org_id,
            member_id=member_id,
            new_role=payload.role,
            actor_id=user.user_id,
            actor_email=user.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return updated


@app.delete("/api/organizations/{org_id}/members/{member_id}")
def delete_org_member_endpoint(
    org_id: str,
    member_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Remove a member from the organization (OWNER or ADMIN)."""
    resolve_org_for_user(user, org_id, permission="manage_members")
    ok = remove_member_from_org(
        organization_id=org_id,
        member_id=member_id,
        actor_id=user.user_id,
        actor_email=user.email,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to remove member")
    return {"status": "removed", "member_id": member_id}


# ---------------------------------------------------------------------------
# Phase 5: Audit Logs & Usage Metrics Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/organizations/{org_id}/audit-logs", response_model=list[AuditLogOut])
def get_org_audit_logs_endpoint(
    org_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
    action: Optional[str] = None,
):
    """Get audit trail of sensitive actions in an organization."""
    resolve_org_for_user(user, org_id, permission="view_audit_logs")
    return get_audit_trail(
        organization_id=org_id,
        limit=limit,
        offset=offset,
        action_filter=action,
    )


@app.get("/api/organizations/{org_id}/usage", response_model=OrganizationUsageOut)
def get_org_usage_endpoint(
    org_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get billing-ready usage metrics and limit utilization for an organization."""
    resolve_org_for_user(user, org_id, permission="view_org")
    try:
        return calculate_organization_usage(org_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc




@app.get("/api/insights/latest", response_model=InsightOut)
def latest_insight(user: AuthenticatedUser = Depends(get_current_user)):
    """Return the most recent weekly AI summary (404 when none exists yet)."""
    insight = get_latest_summary()
    if not insight:
        raise HTTPException(status_code=404, detail="No weekly AI summary generated yet")
    return insight


@app.post("/api/insights/generate", response_model=InsightGenerateResult)
@limiter.limit("2/minute")
def generate_insight(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    """Generate (or refresh) the weekly AI summary on demand.

    Returns 503 with a distinguishing message when the LLM is unconfigured, the
    key is invalid, or the provider is rate-limited — never a silent fake.
    """
    result = generate_weekly_summary()
    if not result.generated:
        raise HTTPException(status_code=503, detail=result.error or "Summary generation failed")
    return result


@app.get("/api/servers/{server_id}/metrics")
def server_metrics(
    server_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    limit: int = 20,
):
    """Return historical metrics for a single server. Authorized via JWT + org membership."""
    authorize_server(user, server_id, permission="view_resources")
    return latest_metrics(server_id, limit=limit)


@app.get("/api/alerts")
def get_all_alerts(user: AuthenticatedUser = Depends(get_current_user)):
    """Return all alerts, resolved and unresolved. Scoped to user's organization."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_alerts")
    return list_alerts(org_id=org_id, unresolved_only=False)



@app.get("/api/costs/account")
def get_account_costs(days: int = 30, user: AuthenticatedUser = Depends(get_current_user)):
    """Get cost breakdown by AWS account for multi-account organizations."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_costs")
    
    # Get the organization's AWS connections
    connections = list_aws_connections_for_org(org_id)
    if not connections:
        return {"days": days, "accounts": [], "total": 0.0, "source": "none"}
    
    # Use the first active connection
    connection = next((c for c in connections if c.get("status") == "active"), connections[0])
    
    try:
        rows = fetch_account_breakdown(days_back=days, connection=connection)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cost Explorer error: {exc}")
    
    # Aggregate by account
    account_totals = {}
    for row in rows:
        account = row["account_id"]
        account_totals[account] = account_totals.get(account, 0.0) + row["amount"]
    
    total = sum(account_totals.values())
    accounts = [
        {"account_id": k, "total_cost": round(v, 2), "percentage": round(v / total * 100, 1) if total > 0 else 0.0}
        for k, v in sorted(account_totals.items(), key=lambda x: x[1], reverse=True)
    ]
    
    return {
        "days": days,
        "accounts": accounts,
        "total": round(total, 2),
        "source": "aws_cost_explorer",
    }


@app.get("/api/costs/services")
def get_service_costs(days: int = 30, user: AuthenticatedUser = Depends(get_current_user)):
    """Get cost breakdown by AWS service."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_costs")
    
    connections = list_aws_connections_for_org(org_id)
    if not connections:
        return {"days": days, "services": [], "total": 0.0, "source": "none"}
    
    connection = next((c for c in connections if c.get("status") == "active"), connections[0])
    
    try:
        rows = fetch_service_breakdown(days_back=days, connection=connection)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cost Explorer error: {exc}")
    
    # Aggregate by service
    service_totals = {}
    for row in rows:
        service = row["service"]
        service_totals[service] = service_totals.get(service, 0.0) + row["amount"]
    
    total = sum(service_totals.values())
    services = [
        {"service": k, "total_cost": round(v, 2), "percentage": round(v / total * 100, 1) if total > 0 else 0.0}
        for k, v in sorted(service_totals.items(), key=lambda x: x[1], reverse=True)
    ]
    
    return {
        "days": days,
        "services": services,
        "total": round(total, 2),
        "source": "aws_cost_explorer",
    }


@app.get("/api/costs/regions")
def get_region_costs(days: int = 30, user: AuthenticatedUser = Depends(get_current_user)):
    """Get cost breakdown by AWS region."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_costs")
    
    connections = list_aws_connections_for_org(org_id)
    if not connections:
        return {"days": days, "regions": [], "total": 0.0, "source": "none"}
    
    connection = next((c for c in connections if c.get("status") == "active"), connections[0])
    
    try:
        rows = fetch_region_breakdown(days_back=days, connection=connection)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cost Explorer error: {exc}")
    
    # Aggregate by region
    region_totals = {}
    for row in rows:
        region = row["region"]
        region_totals[region] = region_totals.get(region, 0.0) + row["amount"]
    
    total = sum(region_totals.values())
    regions = [
        {"region": k, "total_cost": round(v, 2), "percentage": round(v / total * 100, 1) if total > 0 else 0.0}
        for k, v in sorted(region_totals.items(), key=lambda x: x[1], reverse=True)
    ]
    
    return {
        "days": days,
        "regions": regions,
        "total": round(total, 2),
        "source": "aws_cost_explorer",
    }


@app.get("/api/costs/trends/{server_id}")
def get_cost_trends_endpoint(
    server_id: str, days: int = 30, user: AuthenticatedUser = Depends(get_current_user)
):
    """Get cost trends for a specific server with actual vs estimated costs."""
    authorize_server(user, server_id, permission="view_costs")
    
    trends = get_cost_trends(server_id, days=days)
    return trends


@app.get("/api/costs/anomalies/{server_id}")
def get_cost_anomalies_endpoint(
    server_id: str, days: int = 30, user: AuthenticatedUser = Depends(get_current_user)
):
    """Get cost anomalies for a specific server."""
    authorize_server(user, server_id, permission="view_costs")
    
    anomalies = detect_cost_anomalies(server_id, days=days)
    return {"server_id": server_id, "anomalies": anomalies, "count": len(anomalies)}


@app.patch("/api/alerts/{alert_id}/resolve")
def resolve_alert_endpoint(alert_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    """Mark an alert as resolved."""
    org_id, _role = resolve_org_for_user(user, None, permission="manage_alerts")
    result = resolve_alert(alert_id, org_id=org_id)
    if not result:
        raise HTTPException(404, detail=f"Alert {alert_id} not found")
    return result


@app.put("/api/servers/{server_id}/status")
def update_server_status_endpoint(
    server_id: str,
    body: ServerStatusUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Update a server's operational status."""
    server = authorize_server(user, server_id, permission="manage_resources")
    result = update_server_status(server_id, body.status)
    if not result:
        raise HTTPException(500, detail="Failed to update server status")
    
    # Audit log status change
    try:
        log_audit_event(
            organization_id=server.get("organization_id") or "00000000-0000-0000-0000-000000000000",
            action=AuditActions.NODE_STATUS_UPDATED if hasattr(AuditActions, "NODE_STATUS_UPDATED") else "NODE_STATUS_UPDATED",
            resource_type="server",
            actor_id=user.user_id,
            resource_id=server_id,
            metadata={"server_name": server.get("server_name"), "new_status": body.status},
        )
    except Exception:
        pass

    return result


@app.delete("/api/servers/{server_id}", response_model=ServerTerminateResponse)
@app.post("/api/servers/{server_id}/terminate", response_model=ServerTerminateResponse)
def terminate_server_endpoint(
    server_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Terminate and permanently remove a node from fleet management.
    
    1. Validates server existence.
    2. Enforces tenant authorization via JWT + RBAC.
    3. If AWS EC2 node with active connection, attempts AWS instance termination safely.
    4. Deletes/deactivates the node in persistent storage (cascading child telemetry).
    5. Records an audit log event.
    """
    server = authorize_server(user, server_id, permission="manage_resources")
    server_name = server.get("server_name", f"node-{server_id[:8]}")
    prev_status = server.get("status", "active")
    aws_instance_id = server.get("aws_instance_id")
    source = server.get("source", "agent")
    details: dict = {"previous_status": prev_status, "source": source}

    # If AWS EC2 node, attempt termination via AWS credentials if available
    if source == "aws_discovery" and aws_instance_id:
        try:
            conn_id = server.get("aws_connection_id")
            conn = get_aws_connection(conn_id) if conn_id else None
            region = server.get("aws_region") or "us-east-1"
            if conn and conn.get("credentials"):
                import boto3
                creds = conn["credentials"]
                ec2 = boto3.client(
                    "ec2",
                    region_name=region,
                    aws_access_key_id=creds.get("access_key_id"),
                    aws_secret_access_key=creds.get("secret_access_key"),
                    aws_session_token=creds.get("session_token"),
                )
                ec2.terminate_instances(InstanceIds=[aws_instance_id])
                details["aws_terminated"] = True
        except Exception as aws_err:
            details["aws_warning"] = str(aws_err)

    # Delete from database (cascades child tables)
    deleted = delete_server(server_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to terminate and delete server from persistent storage")

    # Record Audit Log
    try:
        log_audit_event(
            organization_id=server.get("organization_id") or "00000000-0000-0000-0000-000000000000",
            action=AuditActions.NODE_TERMINATED if hasattr(AuditActions, "NODE_TERMINATED") else "NODE_TERMINATED",
            resource_type="server",
            actor_id=user.user_id,
            actor_email=user.email,
            resource_id=server_id,
            metadata={
                "server_name": server_name,
                "previous_status": prev_status,
                "resulting_status": "terminated",
                "source": source,
                "aws_instance_id": aws_instance_id,
                "details": details,
            },
        )
    except Exception:
        pass

    return ServerTerminateResponse(
        status="terminated",
        server_id=server_id,
        server_name=server_name,
        message=f"Node '{server_name}' successfully terminated and removed from fleet inventory.",
        details=details,
    )


# ---------------------------------------------------------------------------
# Phase 2: Advanced Anomaly Detection Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/anomalies", response_model=list[AnomalyEventOut])
def get_anomalies(
    server_id: Optional[str] = None,
    severity: Optional[str] = None,
    resolved: Optional[bool] = False,
    limit: int = 50,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List anomaly events, optionally filtered by server, severity, and resolution status."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_anomalies")
    return list_anomaly_events(
        server_id=server_id,
        severity=severity,
        resolved=resolved,
        limit=limit,
        org_id=org_id,
    )


@app.get("/api/anomalies/events", response_model=list[AnomalyEventOut])
def get_all_anomaly_events(
    server_id: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Fetch complete historical log of anomaly events."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_anomalies")
    return list_anomaly_events(
        server_id=server_id,
        severity=severity,
        resolved=None,
        limit=limit,
        org_id=org_id,
    )


@app.patch("/api/anomalies/{event_id}/resolve")
def resolve_anomaly_event_endpoint(
    event_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Mark an anomaly event as resolved."""
    org_id, _role = resolve_org_for_user(user, None, permission="manage_anomalies")
    result = resolve_anomaly_event(event_id, org_id=org_id)
    if not result:
        raise HTTPException(404, detail=f"Anomaly event {event_id} not found")
    return result


@app.get("/api/anomalies/baseline/{server_id}")
def get_server_baseline_envelopes(
    server_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Return historical baseline statistics (rolling & time-aware) and expected envelopes."""
    authorize_server(user, server_id, permission="view_anomalies")
    server = get_server(server_id)
    if not server:
        raise HTTPException(404, detail=f"Server {server_id} not found")

    metrics_history = latest_metrics(server_id, limit=100)
    now = datetime.now(timezone.utc)

    cpu_rolling = compute_rolling_baseline(metrics_history, "cpu_usage")
    cpu_time = compute_time_aware_baseline(metrics_history, "cpu_usage", target_time=now)

    ram_rolling = compute_rolling_baseline(metrics_history, "ram_usage")
    ram_time = compute_time_aware_baseline(metrics_history, "ram_usage", target_time=now)

    net_rolling = compute_rolling_baseline(metrics_history, "network_traffic")
    net_time = compute_time_aware_baseline(metrics_history, "network_traffic", target_time=now)

    return {
        "server_id": server_id,
        "server_name": server.get("server_name", server_id),
        "sample_count": len(metrics_history),
        "baselines": {
            "cpu": {
                "rolling": cpu_rolling,
                "time_aware": cpu_time,
                "current_expected_mean": (cpu_time["mean"] if cpu_time else (cpu_rolling["mean"] if cpu_rolling else None)),
                "current_expected_std": (cpu_time["std"] if cpu_time else (cpu_rolling["std"] if cpu_rolling else None)),
            },
            "ram": {
                "rolling": ram_rolling,
                "time_aware": ram_time,
                "current_expected_mean": (ram_time["mean"] if ram_time else (ram_rolling["mean"] if ram_rolling else None)),
                "current_expected_std": (ram_time["std"] if ram_time else (ram_rolling["std"] if ram_rolling else None)),
            },
            "network": {
                "rolling": net_rolling,
                "time_aware": net_time,
                "current_expected_mean": (net_time["mean"] if net_time else (net_rolling["mean"] if net_rolling else None)),
                "current_expected_std": (net_time["std"] if net_time else (net_rolling["std"] if net_rolling else None)),
            },
        },
    }


# ---------------------------------------------------------------------------
# Phase 2: Cost Optimization Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/optimization/summary", response_model=OptimizationSummaryOut)
def get_optimization_summary(user: AuthenticatedUser = Depends(get_current_user)):
    """Return aggregated cloud cost savings summary, top waste, and opportunity counts."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_optimization")
    servers = list_servers_for_org(org_id=org_id)
    metrics_by_server: dict[str, list[dict]] = {}
    costs_by_server: dict[str, list[dict]] = {}

    for s in servers:
        sid = s["id"]
        metrics_by_server[sid] = latest_metrics(sid, limit=30)
        costs_by_server[sid] = get_daily_costs(server_id=sid, days=30)

    _, summary = run_fleet_optimization_analysis(servers, metrics_by_server, costs_by_server)
    return summary


@app.get("/api/optimization/recommendations", response_model=list[OptimizationRecommendationOut])
def get_optimization_recommendations(
    server_id: Optional[str] = None,
    service_name: Optional[str] = None,
    region: Optional[str] = None,
    severity: Optional[str] = None,
    recommendation_type: Optional[str] = None,
    status: Optional[str] = "active",
    limit: int = 50,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List optimization recommendations filtered by resource, service, region, severity, or type."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_optimization")
    # First query existing stored recommendations
    stored = list_optimization_recommendations(
        org_id=org_id,
        server_id=server_id,
        service_name=service_name,
        region=region,
        severity=severity,
        recommendation_type=recommendation_type,
        status=status,
        limit=limit,
    )
    if stored:
        return stored

    # If table is empty, run live rule-based analysis and persist
    servers = list_servers_for_org(org_id=org_id)
    metrics_by_server = {s["id"]: latest_metrics(s["id"], limit=30) for s in servers}
    costs_by_server = {s["id"]: get_daily_costs(server_id=s["id"], days=30) for s in servers}

    recs, _ = run_fleet_optimization_analysis(servers, metrics_by_server, costs_by_server)
    if recs:
        upsert_optimization_recommendations(recs)
        return list_optimization_recommendations(
            org_id=org_id,
            server_id=server_id,
            service_name=service_name,
            region=region,
            severity=severity,
            recommendation_type=recommendation_type,
            status=status,
            limit=limit,
        )
    return []


@app.post("/api/optimization/analyze", response_model=OptimizationAnalyzeResult)
def trigger_optimization_analysis(user: AuthenticatedUser = Depends(get_current_user)):
    """Trigger cost optimization engine analysis on all resources and update recommendations."""
    org_id, _role = resolve_org_for_user(user, None, permission="manage_optimization")
    servers = list_servers_for_org(org_id=org_id)
    metrics_by_server: dict[str, list[dict]] = {}
    costs_by_server: dict[str, list[dict]] = {}

    for s in servers:
        sid = s["id"]
        metrics_by_server[sid] = latest_metrics(sid, limit=30)
        costs_by_server[sid] = get_daily_costs(server_id=sid, days=30)

    recommendations, summary = run_fleet_optimization_analysis(
        servers, metrics_by_server, costs_by_server
    )
    upsert_optimization_recommendations(recommendations)

    # Evaluate SAVINGS_THRESHOLD alert rules
    try:
        active_rules = list_alert_rules()
        triggered_opt = evaluate_optimization_rules(active_rules, recommendations)
        if triggered_opt:
            active_channels = list_notification_channels()
            for tr in triggered_opt:
                target_types = set(tr.get("target_channels", ["webhook"]))
                relevant_channels = [
                    ch for ch in active_channels
                    if ch.get("channel_type") in target_types or "webhook" in target_types
                ]
                delivery_results = dispatch_alert_notifications(
                    payload=tr["notification_payload"],
                    channels=relevant_channels,
                    cooldown_minutes=tr.get("cooldown_minutes", 60),
                )
                for dr in delivery_results:
                    insert_notification_log({
                        "rule_id": tr.get("rule_id"),
                        "incident_id": None,
                        "server_id": None,
                        "channel_type": dr["channel_type"],
                        "severity": tr["severity"],
                        "recipient_target": dr["recipient_target"],
                        "status": dr["status"],
                        "payload": tr["notification_payload"],
                        "error_message": dr.get("error_message"),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
    except Exception as exc:  # noqa: BLE001
        logger.warning("optimization.alert_dispatch_failed", error=str(exc))

    return OptimizationAnalyzeResult(
        analyzed_servers_count=len(servers),
        recommendations_generated_count=len(recommendations),
        summary=summary,
        recommendations=recommendations,
    )


@app.patch("/api/optimization/recommendations/{recommendation_id}/status")
def update_recommendation_status_endpoint(
    recommendation_id: str,
    payload: RecommendationStatusUpdate = Body(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Update recommendation status (active, applied, or dismissed)."""
    org_id, _role = resolve_org_for_user(user, None, permission="manage_optimization")
    updated = update_optimization_recommendation_status(recommendation_id, payload.status, org_id=org_id)
    if not updated:
        raise HTTPException(404, detail=f"Recommendation {recommendation_id} not found")
    return updated


# ---------------------------------------------------------------------------
# Phase 3: Incident Management Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/incidents", response_model=list[IncidentOut])
def get_incidents(
    status: Optional[str] = None,
    limit: int = 50,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List operational incidents with optional status filter ('open', 'acknowledged', 'resolved')."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_incidents")
    return list_incidents(org_id=org_id, status_filter=status, limit=limit)


@app.get("/api/incidents/{incident_id}", response_model=IncidentOut)
def get_incident_detail(
    incident_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get single incident with full details, chronological timeline, and notes."""
    inc = get_incident(incident_id)
    if not inc:
        raise HTTPException(404, detail=f"Incident {incident_id} not found")
    # Verify the incident belongs to the user's org
    org_id, _role = resolve_org_for_user(user, None, permission="view_incidents")
    if inc.get("organization_id") and inc["organization_id"] != org_id:
        raise AuthorizationError("Access denied to this incident")
    inc["timeline"] = list_incident_timeline(incident_id)
    inc["notes"] = list_incident_notes(incident_id)
    return inc


@app.patch("/api/incidents/{incident_id}/status", response_model=IncidentOut)
def update_incident_status_endpoint(
    incident_id: str,
    payload: IncidentStatusUpdate = Body(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Transition incident status (open -> acknowledged -> resolved) and record timeline event."""
    inc = get_incident(incident_id)
    if not inc:
        raise HTTPException(404, detail=f"Incident {incident_id} not found")
    org_id, _role = resolve_org_for_user(user, None, permission="manage_incidents")
    if inc.get("organization_id") and inc["organization_id"] != org_id:
        raise AuthorizationError("Access denied to this incident")

    updated = update_incident_status(
        incident_id=incident_id,
        new_status=payload.status,
        actor=payload.actor,
        resolution_notes=payload.resolution_notes,
    )
    if not updated:
        raise HTTPException(500, detail="Failed to update incident status")

    # Record timeline event
    insert_incident_timeline_event(
        create_timeline_entry(
            incident_id=incident_id,
            event_type=payload.status.upper(),
            message=f"Status changed to {payload.status.upper()} by {payload.actor}."
            + (f" Root cause / Notes: {payload.resolution_notes}" if payload.resolution_notes else ""),
            actor=payload.actor,
            meta={"previous_status": inc.get("status"), "new_status": payload.status},
        )
    )

    updated["timeline"] = list_incident_timeline(incident_id)
    updated["notes"] = list_incident_notes(incident_id)
    return updated


@app.post("/api/incidents/{incident_id}/notes", response_model=IncidentNoteOut)
def add_incident_note(
    incident_id: str,
    payload: IncidentNoteCreate = Body(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Add an operator note to an incident and record in timeline."""
    org_id, _role = resolve_org_for_user(user, None, permission="manage_incidents")
    inc = get_incident(incident_id)
    if not inc:
        raise HTTPException(404, detail=f"Incident {incident_id} not found")
    if inc.get("organization_id") and inc["organization_id"] != org_id:
        raise AuthorizationError("Access denied to this incident")

    note = insert_incident_note({
        "incident_id": incident_id,
        "author_name": payload.author_name,
        "note_text": payload.note_text,
    })

    # Timeline event
    insert_incident_timeline_event(
        create_timeline_entry(
            incident_id=incident_id,
            event_type="NOTE_ADDED",
            message=f"Note added by {payload.author_name}: \"{payload.note_text[:100]}\"",
            actor=payload.author_name,
        )
    )

    return note


@app.post("/api/incidents/{incident_id}/investigate", response_model=AIInvestigationOut)
def run_incident_ai_investigation(incident_id: str, user: AuthenticatedUser = Depends(get_current_user)):
    """Run grounded AI investigation for an incident using strictly verified backend facts."""
    org_id, _role = resolve_org_for_user(user, None, permission="view_incidents")
    inc = get_incident(incident_id)
    if not inc:
        raise HTTPException(404, detail=f"Incident {incident_id} not found")
    if inc.get("organization_id") and inc["organization_id"] != org_id:
        raise AuthorizationError("Access denied to this incident")

    server_id = str(inc.get("server_id", ""))
    server = get_server(server_id) if server_id else None
    recent_metrics = latest_metrics(server_id, limit=30) if server_id else []
    baseline_info = None
    if server_id:
        try:
            baseline_info = get_server_baseline_envelopes(server_id)
        except Exception:  # noqa: BLE001
            baseline_info = None

    recs = list_optimization_recommendations(server_id=server_id, limit=5) if server_id else []

    facts = build_incident_facts(
        incident=inc,
        server=server,
        recent_metrics=recent_metrics,
        baseline_info=baseline_info,
        recommendations=recs,
    )

    investigation = run_ai_incident_investigation(facts)

    # Persist the investigation to the incident record
    create_or_update_incident({
        "id": incident_id,
        "ai_investigation": investigation,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    # Append timeline entry
    insert_incident_timeline_event(
        create_timeline_entry(
            incident_id=incident_id,
            event_type="AI_INVESTIGATION",
            message=f"AI Investigation conducted ({investigation.get('provider') or 'Deterministic Fallback'}).",
            actor="CloudPulseAI",
            meta={"summary": investigation.get("summary")},
        )
    )

    return investigation


# ---------------------------------------------------------------------------
# Phase 3: Alert Rules Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/alerts/rules", response_model=list[AlertRuleOut])
def get_alert_rules():
    """List all custom alert rules."""
    return list_alert_rules()


@app.post("/api/alerts/rules", response_model=AlertRuleOut)
def save_alert_rule(payload: AlertRuleCreate = Body(...)):
    """Create or update an alert rule."""
    rule_data = payload.model_dump()
    return upsert_alert_rule(rule_data)


@app.delete("/api/alerts/rules/{rule_id}")
def remove_alert_rule(rule_id: str):
    """Delete an alert rule by ID."""
    success = delete_alert_rule(rule_id)
    if not success:
        raise HTTPException(500, detail="Failed to delete alert rule")
    return {"status": "deleted", "rule_id": rule_id}


# ---------------------------------------------------------------------------
# Phase 3: Notification Channels Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/alerts/channels", response_model=list[NotificationChannelOut])
def get_notification_channels():
    """List all configured notification channels."""
    return list_notification_channels()


@app.post("/api/alerts/channels", response_model=NotificationChannelOut)
def save_notification_channel(payload: NotificationChannelCreate = Body(...)):
    """Create or update a notification channel (Webhook, Discord, Slack, Email)."""
    channel_data = payload.model_dump()
    return upsert_notification_channel(channel_data)


@app.delete("/api/alerts/channels/{channel_id}")
def remove_notification_channel(channel_id: str):
    """Delete a notification channel."""
    success = delete_notification_channel(channel_id)
    if not success:
        raise HTTPException(500, detail="Failed to delete notification channel")
    return {"status": "deleted", "channel_id": channel_id}


@app.post("/api/alerts/channels/{channel_id}/test")
def test_notification_channel(channel_id: str):
    """Send a test notification payload to a configured channel."""
    channels = list_notification_channels()
    target_ch = next((c for c in channels if str(c.get("id")) == str(channel_id)), None)
    if not target_ch:
        raise HTTPException(404, detail=f"Channel {channel_id} not found")

    test_payload = {
        "title": "CloudPulse AI Test Notification",
        "message": f"This is a test notification from CloudPulse AI for channel '{target_ch.get('name')}'.",
        "severity": "info",
        "server_id": "test-instance",
        "server_name": "Test Server (us-east-1)",
        "alert_type": "TEST_ALERT",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "meta": {"test": True},
    }

    ch_type = target_ch.get("channel_type", "webhook").lower()
    config = target_ch.get("config", {})

    result = None
    if ch_type == "webhook" and config.get("url"):
        result = send_generic_webhook(config["url"], test_payload, config.get("secret"))
    elif ch_type == "discord" and config.get("url"):
        result = send_discord_webhook(config["url"], test_payload)
    elif ch_type == "slack" and config.get("url"):
        result = send_slack_webhook(config["url"], test_payload)
    elif ch_type == "email" and config.get("email"):
        result = send_email_alert(config["email"], test_payload)
    else:
        raise HTTPException(400, detail="Channel configuration missing target URL or email")

    insert_notification_log({
        "rule_id": None,
        "incident_id": None,
        "server_id": None,
        "channel_type": ch_type,
        "severity": "info",
        "recipient_target": result["recipient_target"],
        "status": result["status"],
        "payload": test_payload,
        "error_message": result.get("error_message"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    return result


@app.get("/api/alerts/logs", response_model=list[NotificationLogOut])
def get_notification_logs(incident_id: Optional[str] = None, limit: int = 50):
    """List recent notification delivery logs."""
    return list_notification_logs(incident_id=incident_id, limit=limit)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


