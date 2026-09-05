"""Pydantic request / response models for CloudPulse AI."""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Metrics ingestion
# ---------------------------------------------------------------------------

class MetricPayload(BaseModel):
    # NOTE: server_id is intentionally absent — the target server is
    # identified server-side by the ingestion token (Authorization: Bearer).
    cpu_usage: float = Field(..., ge=0.0, le=100.0)
    ram_usage: float = Field(..., ge=0.0, le=100.0)
    network_traffic: float = Field(..., ge=0.0)
    # Expanded telemetry metrics (optional for backwards compatibility)
    disk_usage: float | None = Field(default=None, ge=0.0, le=100.0)
    disk_io: dict | None = None
    system_uptime: float | None = None
    load_average: list[float] | None = None
    process_count: int | None = None
    network_stats: dict | None = None


class MetricResponse(BaseModel):
    id: UUID
    server_id: UUID
    cpu_usage: float
    ram_usage: float
    network_traffic: float
    disk_usage: float | None = None
    disk_io: dict | None = None
    system_uptime: float | None = None
    load_average: list[float] | None = None
    process_count: int | None = None
    network_stats: dict | None = None
    recorded_at: datetime
    alert_triggered: bool = False


# ---------------------------------------------------------------------------
# Server status
# ---------------------------------------------------------------------------

class ServerOut(BaseModel):
    id: UUID
    server_name: str
    ip_address: str | None = None
    status: str = "active"
    specifications: dict | None = None
    source: str = "agent"  # "agent" | "aws_discovery"
    aws_instance_id: str | None = None
    aws_region: str | None = None
    aws_availability_zone: str | None = None
    aws_state: str | None = None
    aws_launch_time: datetime | None = None
    aws_tags: dict | None = None
    last_discovered_at: datetime | None = None
    created_at: datetime | None = None


class ServerStatusResponse(BaseModel):
    servers: list[ServerOut]
    metrics: dict[str, list[dict]]  # server_id → list of metric rows
    active_alerts: list[dict]
    summary: dict = {}
    costs: dict[str, list[dict]] = {}  # server_id → daily cost rows (real spend)
    cloud: dict = {}  # cloud-connection status (see CloudStatus)
    discovery: dict = {}  # discovery status summary


# ---------------------------------------------------------------------------
# Cloud cost & discovery integration (AWS EC2 & Cost Explorer)
# ---------------------------------------------------------------------------

class CloudStatus(BaseModel):
    connected: bool = False
    provider: str | None = None
    cost_tag_key: str = "server"
    region: str = "us-east-1"
    last_sync: str | None = None  # ISO date of the most recent daily cost pulled
    last_discovery: str | None = None  # ISO datetime of most recent discovery run
    discovered_count: int = 0
    days_of_data: int = 0
    cost_source: str = "simulated"  # "aws_cost_explorer" | "simulated"
    error: str | None = None


class SyncResult(BaseModel):
    days_synced: int = 0
    matched: int = 0  # resource-tag values mapped to a known server
    unmatched: list[str] = []  # tag values with no matching server
    total_amount: float = 0.0
    error: str | None = None


class DiscoveryResult(BaseModel):
    discovered_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    matched_count: int = 0
    instances: list[dict] = []
    region: str = "us-east-1"
    error: str | None = None



# ---------------------------------------------------------------------------
# Server status update
# ---------------------------------------------------------------------------

class ServerStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(active|warning|critical|idle)$")


# ---------------------------------------------------------------------------
# Alert resolve
# ---------------------------------------------------------------------------

class AlertResolveResponse(BaseModel):
    id: UUID
    server_id: UUID
    alert_type: str
    message: str
    resolved: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Weekly AI insights
# ---------------------------------------------------------------------------

class InsightOut(BaseModel):
    id: UUID
    period_start: date
    period_end: date
    summary: str
    provider: str | None = None
    model: str | None = None
    meta: dict = {}  # server_count, alert_count, total_cost, generation_ms
    generated_at: datetime | None = None


class InsightGenerateResult(BaseModel):
    generated: bool = False
    insight: InsightOut | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Phase 2: Anomaly Events & Cost Optimization Models
# ---------------------------------------------------------------------------

class AnomalyEventOut(BaseModel):
    id: UUID
    server_id: UUID
    metric_name: str
    current_value: float
    baseline_value: float
    deviation_sigma: float | None = None
    severity: str = "warning"  # "info" | "warning" | "critical"
    consecutive_count: int = 1
    duration_seconds: int = 0
    detection_method: str
    explanation: str
    meta: dict = {}
    resolved: bool = False
    servers: dict | None = None
    created_at: datetime | None = None


class OptimizationRecommendationOut(BaseModel):
    id: UUID | str
    server_id: UUID | str
    service_name: str = "ec2"
    resource_id: str | None = None
    resource_name: str
    region: str | None = "us-east-1"
    recommendation_type: str  # "IDLE_RESOURCE", "LOW_UTILIZATION", "RIGHT_SIZING", "COST_SPIKE"
    severity: str = "warning"  # "info", "warning", "critical"
    current_cost_monthly: float = 0.0
    estimated_savings_monthly: float = 0.0
    estimated_avoidable_cost: float = 0.0
    confidence: str = "HIGH"  # "HIGH", "MEDIUM", "LOW"
    pricing_source: str = "aws_catalog"
    problem_summary: str
    action_recommendation: str
    target_resource_type: str | None = None
    evidence: dict = {}
    status: str = "active"  # "active", "applied", "dismissed"
    servers: dict | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class OptimizationSummaryOut(BaseModel):
    total_monthly_spend: float = 0.0
    estimated_avoidable_spend: float = 0.0
    potential_monthly_savings: float = 0.0
    total_opportunities_count: int = 0
    highest_cost_resources: list[dict] = []
    highest_savings_opportunities: list[dict] = []
    by_type_counts: dict[str, int] = {}
    by_severity_counts: dict[str, int] = {}


class OptimizationAnalyzeResult(BaseModel):
    analyzed_servers_count: int = 0
    recommendations_generated_count: int = 0
    summary: OptimizationSummaryOut
    recommendations: list[OptimizationRecommendationOut] = []


class RecommendationStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(active|applied|dismissed)$")


# ---------------------------------------------------------------------------
# Phase 3: Smart Alerting & Notification Models
# ---------------------------------------------------------------------------

class NotificationChannelCreate(BaseModel):
    name: str
    channel_type: str = Field(..., pattern=r"^(webhook|discord|slack|email)$")
    config: dict = {}
    enabled: bool = True


class NotificationChannelOut(BaseModel):
    id: UUID | str
    name: str
    channel_type: str
    config: dict = {}
    enabled: bool = True
    created_at: datetime | str | None = None


class AlertRuleCreate(BaseModel):
    name: str
    rule_type: str = Field(..., pattern=r"^(CPU_ANOMALY|RAM_ANOMALY|NETWORK_ANOMALY|IDLE_RESOURCE|BUDGET_SPIKE|SAVINGS_THRESHOLD|CUSTOM)$")
    condition_config: dict = {}
    severity: str = "warning"
    cooldown_minutes: int = 15
    channels: list[str] = ["webhook"]
    enabled: bool = True


class AlertRuleOut(BaseModel):
    id: UUID | str
    name: str
    rule_type: str
    condition_config: dict = {}
    severity: str = "warning"
    cooldown_minutes: int = 15
    channels: list[str] = ["webhook"]
    enabled: bool = True
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class NotificationLogOut(BaseModel):
    id: UUID | str
    rule_id: UUID | str | None = None
    incident_id: UUID | str | None = None
    server_id: UUID | str | None = None
    channel_type: str
    severity: str
    recipient_target: str | None = None
    status: str
    payload: dict = {}
    error_message: str | None = None
    created_at: datetime | str | None = None


# ---------------------------------------------------------------------------
# Phase 3: Incident Lifecycle Models
# ---------------------------------------------------------------------------

class IncidentCreate(BaseModel):
    server_id: UUID | str
    title: str
    description: str
    incident_type: str
    severity: str = "warning"
    root_cause_summary: str | None = None


class IncidentStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(open|acknowledged|resolved)$")
    actor: str = "Operator"
    resolution_notes: str | None = None


class IncidentNoteCreate(BaseModel):
    author_name: str = "Operator"
    note_text: str


class IncidentNoteOut(BaseModel):
    id: UUID | str
    incident_id: UUID | str
    author_name: str
    note_text: str
    created_at: datetime | str | None = None


class IncidentTimelineOut(BaseModel):
    id: UUID | str
    incident_id: UUID | str
    event_type: str
    actor: str
    message: str
    meta: dict = {}
    created_at: datetime | str | None = None


class IncidentOut(BaseModel):
    id: UUID | str
    server_id: UUID | str
    title: str
    description: str
    incident_type: str
    severity: str = "warning"
    status: str = "open"
    root_cause_summary: str | None = None
    ai_investigation: dict = {}
    acknowledged_at: datetime | str | None = None
    acknowledged_by: str | None = None
    resolved_at: datetime | str | None = None
    resolved_by: str | None = None
    servers: dict | None = None
    server_details: dict | None = None
    timeline: list[IncidentTimelineOut] = []
    notes: list[IncidentNoteOut] = []
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class AIInvestigationOut(BaseModel):
    summary: str
    incident_explanation: str
    cost_impact_explanation: str
    root_cause_hypotheses: list[str] = []
    prioritized_actions: list[dict] = []
    grounded_facts: dict = {}
    provider: str | None = None
    model: str | None = None
    is_fallback: bool = False


# ---------------------------------------------------------------------------
# Phase 4: Multi-Tenant AWS Connection Models
# ---------------------------------------------------------------------------

class AWSConnectionInitiateRequest(BaseModel):
    display_name: str = "AWS Production Account"
    region: str = "us-east-1"


class AWSConnectionInitiateResponse(BaseModel):
    external_id: str
    cloudpulse_account_id: str
    trust_policy: dict
    permissions_policy: dict
    cloudformation_quick_create_url: str
    region: str = "us-east-1"


class AWSConnectionCreate(BaseModel):
    role_arn: str
    external_id: str
    display_name: str = "AWS Account"
    region: str = "us-east-1"
    aws_account_id: str | None = None


class AWSConnectionUpdate(BaseModel):
    display_name: str | None = None
    region: str | None = None
    role_arn: str | None = None


class AWSConnectionOut(BaseModel):
    id: UUID | str
    user_id: UUID | str | None = None
    organization_id: UUID | str | None = None
    aws_account_id: str | None = None
    role_arn: str | None = None
    external_id: str
    region: str = "us-east-1"
    display_name: str = "AWS Account"
    status: str = "pending"  # "pending", "connected", "error", "disconnected"
    health_status: str = "UNVERIFIED"  # "HEALTHY", "DEGRADED", "ERROR", "UNVERIFIED"
    health_checks: dict = {}
    error_message: str | None = None
    last_verified_at: datetime | str | None = None
    last_sync_at: datetime | str | None = None
    last_sync_started: datetime | str | None = None
    last_sync_completed: datetime | str | None = None
    sync_status: str = "IDLE"  # "IDLE", "SYNCING", "SUCCESS", "FAILED"
    sync_error: str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class AWSConnectionVerifyResponse(BaseModel):
    success: bool
    status: str
    aws_account_id: str | None = None
    error_message: str | None = None
    connection: AWSConnectionOut | None = None


# ---------------------------------------------------------------------------
# Phase 5: Organizations, RBAC, Audit Logs & Centralized Sync Models
# ---------------------------------------------------------------------------

class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    slug: str | None = None
    plan_tier: str = "free"


class OrganizationUpdate(BaseModel):
    name: str | None = None
    plan_tier: str | None = None
    max_aws_connections: int | None = None
    retention_days: int | None = None


class OrganizationMemberOut(BaseModel):
    id: UUID | str
    organization_id: UUID | str
    user_id: UUID | str
    role: str  # "OWNER", "ADMIN", "MEMBER", "VIEWER"
    invited_email: str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class OrganizationMemberInvite(BaseModel):
    email: str
    role: str = "MEMBER"  # "ADMIN", "MEMBER", "VIEWER"


class OrganizationMemberUpdateRole(BaseModel):
    role: str  # "OWNER", "ADMIN", "MEMBER", "VIEWER"


class OrganizationOut(BaseModel):
    id: UUID | str
    name: str
    slug: str
    plan_tier: str = "free"
    max_aws_connections: int = 5
    retention_days: int = 30
    user_role: str | None = None  # Role of the current requesting user
    members_count: int = 1
    aws_connections_count: int = 0
    servers_count: int = 0
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class AuditLogOut(BaseModel):
    id: UUID | str
    organization_id: UUID | str
    actor_id: UUID | str | None = None
    actor_email: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    metadata: dict = {}
    created_at: datetime | str | None = None


class AuditLogCreate(BaseModel):
    organization_id: UUID | str
    actor_id: UUID | str | None = None
    actor_email: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    metadata: dict = {}


class AWSHealthCheckItem(BaseModel):
    status: str = "PASS"  # "PASS", "FAIL", "SKIPPED"
    message: str | None = None
    latency_ms: float | None = None
    error: str | None = None


class AWSHealthDiagnosticResponse(BaseModel):
    connection_id: str
    health_status: str  # "HEALTHY", "DEGRADED", "ERROR", "UNVERIFIED"
    checks: dict[str, AWSHealthCheckItem]
    diagnosed_at: datetime | str
    summary: str


class OrganizationUsageOut(BaseModel):
    organization_id: str
    plan_tier: str
    connected_aws_accounts: int
    max_aws_connections: int
    monitored_nodes: int
    active_alerts: int
    retention_days: int
    telemetry_metrics_24h: int
    telemetry_metrics_30d: int


class SyncEngineResult(BaseModel):
    status: str  # "SUCCESS", "FAILED"
    connection_id: str
    organization_id: str
    duration_ms: float
    ec2_discovery: DiscoveryResult
    cost_sync: SyncResult
    anomalies_detected: int = 0
    recommendations_generated: int = 0
    error: str | None = None


# Resolve Pydantic v2 type annotations
MetricPayload.model_rebuild()
MetricResponse.model_rebuild()
ServerOut.model_rebuild()
ServerStatusResponse.model_rebuild()
CloudStatus.model_rebuild()
SyncResult.model_rebuild()
DiscoveryResult.model_rebuild()
AnomalyEventOut.model_rebuild()
OptimizationRecommendationOut.model_rebuild()
OptimizationSummaryOut.model_rebuild()
OptimizationAnalyzeResult.model_rebuild()
NotificationChannelOut.model_rebuild()
AlertRuleOut.model_rebuild()
NotificationLogOut.model_rebuild()
IncidentOut.model_rebuild()
IncidentTimelineOut.model_rebuild()
IncidentNoteOut.model_rebuild()
AIInvestigationOut.model_rebuild()
AWSConnectionInitiateResponse.model_rebuild()
AWSConnectionOut.model_rebuild()
AWSConnectionVerifyResponse.model_rebuild()
OrganizationCreate.model_rebuild()
OrganizationUpdate.model_rebuild()
OrganizationOut.model_rebuild()
OrganizationMemberOut.model_rebuild()
OrganizationMemberInvite.model_rebuild()
OrganizationMemberUpdateRole.model_rebuild()
AuditLogOut.model_rebuild()
AuditLogCreate.model_rebuild()
AWSHealthDiagnosticResponse.model_rebuild()
OrganizationUsageOut.model_rebuild()
SyncEngineResult.model_rebuild()





