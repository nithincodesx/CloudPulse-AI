"""Pydantic request / response models for CloudPulse AI."""

from __future__ import annotations

from datetime import datetime
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
    estimated_cost_per_hour: float = Field(..., ge=0.0)


class MetricResponse(BaseModel):
    id: UUID
    server_id: UUID
    cpu_usage: float
    ram_usage: float
    network_traffic: float
    estimated_cost_per_hour: float
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
