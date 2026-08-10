"""Pydantic request / response models for CloudPulse AI."""

from __future__ import annotations

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
    # Cost is also absent — real spend is pulled from AWS Cost Explorer and
    # stored in daily_costs; the agent never reports fabricated costs.
    cpu_usage: float = Field(..., ge=0.0, le=100.0)
    ram_usage: float = Field(..., ge=0.0, le=100.0)
    network_traffic: float = Field(..., ge=0.0)


class MetricResponse(BaseModel):
    id: UUID
    server_id: UUID
    cpu_usage: float
    ram_usage: float
    network_traffic: float
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
    created_at: datetime | None = None


class ServerStatusResponse(BaseModel):
    servers: list[ServerOut]
    metrics: dict[str, list[dict]]  # server_id → list of metric rows
    active_alerts: list[dict]
    summary: dict = {}
    costs: dict[str, list[dict]] = {}  # server_id → daily cost rows (real spend)
    cloud: dict = {}  # cloud-connection status (see CloudStatus)


# ---------------------------------------------------------------------------
# Cloud cost integration (AWS Cost Explorer)
# ---------------------------------------------------------------------------

class CloudStatus(BaseModel):
    connected: bool = False
    provider: str | None = None
    cost_tag_key: str = "server"
    last_sync: str | None = None  # ISO date of the most recent daily cost pulled
    days_of_data: int = 0
    cost_source: str = "simulated"  # "aws_cost_explorer" | "simulated"
    error: str | None = None


class SyncResult(BaseModel):
    days_synced: int = 0
    matched: int = 0  # resource-tag values mapped to a known server
    unmatched: list[str] = []  # tag values with no matching server
    total_amount: float = 0.0
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
