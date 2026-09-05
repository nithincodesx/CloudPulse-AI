"""Centralized, Idempotent AWS Synchronization Engine for CloudPulse-AI.

Coordinates cross-account EC2 discovery, tag mapping, Cost Explorer daily spend ingestion,
anomaly evaluation, and cost optimization recommendations into a single unified pipeline.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from audit_service import AuditActions, log_audit_event
from aws_credentials import diagnose_connection_health
from aws_discovery import sync_aws_resources
from aws_cost import sync_daily_costs
from cost_optimizer import run_fleet_optimization_analysis
from anomaly import check_advanced_anomalies
from database import (
    get_aws_connection,
    update_aws_connection,
    list_servers_for_connection,
    latest_metrics,
)

logger = logging.getLogger("cloudpulse.sync_engine")


def run_centralized_sync(
    connection_id: str | UUID,
    organization_id: str | UUID | None = None,
    actor_id: str | UUID | None = None,
    actor_email: str | None = None,
) -> dict[str, Any]:
    """Executes a full idempotent sync pipeline for an AWS Connection."""
    conn_id_str = str(connection_id)
    t_start = time.perf_counter()
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_aws_connection(conn_id_str)
    if not conn:
        raise ValueError(f"AWS connection {conn_id_str} not found")

    org_id = organization_id or conn.get("organization_id")

    # Mark sync started
    update_aws_connection(conn_id_str, {
        "sync_status": "SYNCING",
        "last_sync_started": now_iso,
        "sync_error": None,
    })

    try:
        # Step 1: Health Diagnostic & Credential Verification
        health_diag = diagnose_connection_health(conn)
        update_aws_connection(conn_id_str, {
            "health_status": health_diag["health_status"],
            "health_checks": health_diag["checks"],
        })

        if health_diag["health_status"] == "ERROR":
            raise RuntimeError(health_diag["summary"])

        # Step 2: EC2 Discovery (Idempotent upsert & tag mapping)
        logger.info("sync_engine.ec2_discovery.start", connection_id=conn_id_str)
        disc_result = sync_aws_resources(
            region=conn.get("region"),
            connection=conn,
            owner_id=conn.get("user_id"),
        )

        # Step 3: Cost Explorer Daily Spend (Idempotent upsert to daily_costs)
        logger.info("sync_engine.cost_sync.start", connection_id=conn_id_str)
        cost_result = sync_daily_costs(
            connection=conn,
            days_back=30,
        )

        # Step 4: Run Anomaly & Optimization evaluations on updated data
        anomalies_detected = 0
        recommendations_count = 0
        servers = list_servers_for_connection(conn_id_str)
        for srv in servers:
            try:
                metrics = latest_metrics(srv["id"], limit=60)
                if metrics:
                    latest = metrics[-1]
                    anoms = check_advanced_anomalies(srv["id"], latest, metrics)
                    anomalies_detected += len(anoms)
            except Exception as e:
                logger.warning("Anomaly check failed during sync for server %s: %s", srv["id"], e)

        try:
            opt_summary = run_fleet_optimization_analysis()
            recommendations_count = opt_summary.get("total_opportunities_count", 0)
        except Exception as e:
            logger.warning("Cost optimization analysis failed during sync: %s", e)

        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        completed_iso = datetime.now(timezone.utc).isoformat()

        # Mark sync success
        update_aws_connection(conn_id_str, {
            "status": "connected",
            "sync_status": "SUCCESS",
            "last_sync_completed": completed_iso,
            "last_sync_at": completed_iso,
            "sync_error": None,
        })

        if org_id:
            log_audit_event(
                organization_id=org_id,
                action=AuditActions.SYNC_COMPLETED,
                resource_type="AWS_CONNECTION",
                actor_id=actor_id,
                actor_email=actor_email,
                resource_id=conn_id_str,
                metadata={
                    "discovered_count": disc_result.get("discovered_count", 0),
                    "days_synced": cost_result.get("days_synced", 0),
                    "anomalies_detected": anomalies_detected,
                    "recommendations_count": recommendations_count,
                    "duration_ms": duration_ms,
                },
            )

        return {
            "status": "SUCCESS",
            "connection_id": conn_id_str,
            "organization_id": str(org_id) if org_id else None,
            "duration_ms": duration_ms,
            "ec2_discovery": disc_result,
            "cost_sync": cost_result,
            "anomalies_detected": anomalies_detected,
            "recommendations_generated": recommendations_count,
            "error": None,
        }

    except Exception as exc:
        duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
        err_msg = str(exc)
        logger.error("sync_engine.failed", connection_id=conn_id_str, error=err_msg)

        update_aws_connection(conn_id_str, {
            "sync_status": "FAILED",
            "sync_error": err_msg,
        })

        if org_id:
            log_audit_event(
                organization_id=org_id,
                action=AuditActions.SYNC_FAILED,
                resource_type="AWS_CONNECTION",
                actor_id=actor_id,
                actor_email=actor_email,
                resource_id=conn_id_str,
                metadata={"error": err_msg, "duration_ms": duration_ms},
            )

        return {
            "status": "FAILED",
            "connection_id": conn_id_str,
            "organization_id": str(org_id) if org_id else None,
            "duration_ms": duration_ms,
            "ec2_discovery": {"discovered_count": 0, "error": err_msg},
            "cost_sync": {"days_synced": 0, "error": err_msg},
            "anomalies_detected": 0,
            "recommendations_generated": 0,
            "error": err_msg,
        }
