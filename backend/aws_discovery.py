"""AWS Resource Discovery Service for CloudPulse AI.

Provides modular discovery of AWS infrastructure (starting with EC2) and
integrates discovered instances idempotently into the CloudPulse server model.

Supports Multi-Tenant cross-account AssumeRole connections as well as
local developer .env fallback.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv

from aws_credentials import get_aws_client
from database import (
    get_server_by_aws_instance_id,
    list_servers,
    upsert_discovered_server,
)
from logging_conf import get_logger
from models import DiscoveryResult

load_dotenv()

logger = get_logger("backend.aws_discovery")

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
AWS_REGION = os.getenv("AWS_REGION", "us-east-1").strip()
AWS_COST_TAG_KEY = os.getenv("AWS_COST_TAG_KEY", "server").strip()

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    _BOTO3_AVAILABLE = True
except ImportError:  # pragma: no cover
    boto3 = None
    _BOTO3_AVAILABLE = False


def discovery_configured(connection: Optional[dict[str, Any]] = None) -> bool:
    """True when an active AWS connection or developer credentials are present and boto3 is installed."""
    if not _BOTO3_AVAILABLE:
        return False
    if connection and connection.get("role_arn") and connection.get("external_id"):
        return True
    return bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)


class ResourceDiscoverer(ABC):
    """Abstract base class for AWS resource discovery services."""

    @abstractmethod
    def discover(self, region: str | None = None) -> list[dict[str, Any]]:
        """Discover resources and return normalized metadata dictionaries."""
        pass


class EC2Discoverer(ResourceDiscoverer):
    """AWS EC2 instance discovery provider."""

    def __init__(
        self,
        region: str | None = None,
        connection: Optional[dict[str, Any]] = None,
    ) -> None:
        self.connection = connection
        self.region = region or (connection.get("region") if connection else None) or AWS_REGION

    def _get_ec2_client(self):
        if not discovery_configured(self.connection):
            raise RuntimeError(
                "AWS not configured. Connect an AWS account in Dashboard or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY."
            )
        return get_aws_client("ec2", connection=self.connection, region=self.region)

    def discover(self, region: str | None = None) -> list[dict[str, Any]]:
        """Fetch EC2 instances from the configured AWS account and region."""
        if region:
            self.region = region

        client = self._get_ec2_client()
        logger.info("aws.discovery.ec2.start", region=self.region)

        try:
            paginator = client.get_paginator("describe_instances")
            page_iterator = paginator.paginate(
                Filters=[
                    {
                        "Name": "instance-state-name",
                        "Values": ["pending", "running", "shutting-down", "stopping", "stopped"],
                    }
                ]
            )

            discovered_instances: list[dict[str, Any]] = []

            for page in page_iterator:
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        parsed = self._parse_instance(instance)
                        if parsed:
                            discovered_instances.append(parsed)

            logger.info(
                "aws.discovery.ec2.complete",
                region=self.region,
                count=len(discovered_instances),
            )
            return discovered_instances

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "ClientError")
            error_msg = exc.response.get("Error", {}).get("Message", str(exc))
            logger.error(
                "aws.discovery.ec2.client_error",
                code=error_code,
                message=error_msg,
                region=self.region,
            )
            raise RuntimeError(f"AWS EC2 Discovery failed ({error_code}): {error_msg}") from exc
        except BotoCoreError as exc:
            logger.error("aws.discovery.ec2.botocore_error", error=str(exc))
            raise RuntimeError(f"AWS EC2 Discovery error: {exc}") from exc


    def _parse_instance(self, instance: dict[str, Any]) -> dict[str, Any]:
        """Normalize EC2 raw describe_instances item into CloudPulse metadata schema."""
        instance_id = instance.get("InstanceId", "")
        instance_type = instance.get("InstanceType", "unknown")
        state_dict = instance.get("State", {})
        state_name = state_dict.get("Name", "unknown")
        launch_time = instance.get("LaunchTime")
        if hasattr(launch_time, "isoformat"):
            launch_time_str = launch_time.isoformat()
        elif launch_time:
            launch_time_str = str(launch_time)
        else:
            launch_time_str = None

        placement = instance.get("Placement", {})
        az = placement.get("AvailabilityZone")

        # Tags parsing
        raw_tags = instance.get("Tags", [])
        tags: dict[str, str] = {t.get("Key", ""): t.get("Value", "") for t in raw_tags if t.get("Key")}

        # Name heuristic: Name tag -> instance_id
        name = tags.get("Name") or f"aws-{instance_id}"

        # IP address heuristic: PublicIpAddress -> PrivateIpAddress -> "auto-assigned"
        ip = instance.get("PublicIpAddress") or instance.get("PrivateIpAddress") or "auto-assigned"

        architecture = instance.get("Architecture", "x86_64")
        hypervisor = instance.get("Hypervisor", "xen")

        # Derive approximate vcpus and ram_gb from common EC2 sizing heuristics if not explicitly known
        vcpus, ram_gb = _approximate_instance_specs(instance_type)

        specifications = {
            "type": instance_type,
            "architecture": architecture,
            "hypervisor": hypervisor,
            "vcpus": vcpus,
            "ram_gb": ram_gb,
        }

        return {
            "aws_instance_id": instance_id,
            "server_name": name,
            "ip_address": ip,
            "aws_region": self.region,
            "aws_availability_zone": az,
            "aws_state": state_name,
            "aws_launch_time": launch_time_str,
            "aws_tags": tags,
            "specifications": specifications,
        }


def _approximate_instance_specs(instance_type: str) -> tuple[int, int]:
    """Estimate vCPU and RAM from common instance type names."""
    parts = instance_type.split(".")
    size = parts[1] if len(parts) > 1 else "medium"

    specs_map = {
        "nano": (1, 1),
        "micro": (1, 1),
        "small": (1, 2),
        "medium": (2, 4),
        "large": (2, 8),
        "xlarge": (4, 16),
        "2xlarge": (8, 32),
        "4xlarge": (16, 64),
        "8xlarge": (32, 128),
        "16xlarge": (64, 256),
    }
    return specs_map.get(size, (2, 4))


def _map_aws_state_to_status(aws_state: str) -> str:
    """Map AWS EC2 state to CloudPulse server status enum."""
    state = aws_state.lower()
    if state == "running":
        return "active"
    elif state == "pending":
        return "warning"
    elif state in ("stopped", "shutting-down"):
        return "idle"
    return "active"


def sync_aws_resources(
    region: str | None = None,
    connection: Optional[dict[str, Any]] = None,
) -> DiscoveryResult:
    """Run AWS discovery across services and upsert servers into the database."""
    if not discovery_configured(connection):
        return DiscoveryResult(error="AWS not configured — Connect an AWS account in the dashboard.")

    effective_region = region or (connection.get("region") if connection else None) or AWS_REGION
    discoverer = EC2Discoverer(region=effective_region, connection=connection)

    try:
        instances = discoverer.discover(region=effective_region)
    except Exception as exc:  # noqa: BLE001
        logger.error("aws.discovery.sync_failed", error=str(exc))
        return DiscoveryResult(region=effective_region, error=str(exc))

    existing_servers = list_servers()
    created_count = 0
    updated_count = 0
    matched_count = 0

    now_iso = datetime.now(timezone.utc).isoformat()
    conn_id = connection.get("id") if connection else None

    for item in instances:
        instance_id = item["aws_instance_id"]
        instance_name = item["server_name"]
        tags = item.get("aws_tags", {})
        ip_addr = item.get("ip_address")

        # 1. Match by aws_instance_id
        matched_server = get_server_by_aws_instance_id(instance_id)

        # 2. If not matched, try matching existing server by cost_tag / name / IP
        if not matched_server:
            cost_tag_val = tags.get(AWS_COST_TAG_KEY) or tags.get("server") or tags.get("Server")
            want_tags = [v.strip().lower() for v in [cost_tag_val, instance_name, ip_addr] if v]

            for s in existing_servers:
                s_cost_tag = (s.get("cost_tag") or "").strip().lower()
                s_name = (s.get("server_name") or "").strip().lower()
                s_ip = (s.get("ip_address") or "").strip().lower()

                if s_cost_tag and s_cost_tag in want_tags:
                    matched_server = s
                    break
                if s_name and s_name in want_tags:
                    matched_server = s
                    break
                if s_ip and s_ip in want_tags:
                    matched_server = s
                    break

        status = _map_aws_state_to_status(item.get("aws_state", "running"))

        if matched_server:
            matched_count += 1
            # Update existing server record
            payload = {
                "id": matched_server["id"],
                "server_name": matched_server.get("server_name") or instance_name,
                "source": "aws_discovery",
                "aws_instance_id": instance_id,
                "aws_region": item.get("aws_region"),
                "aws_availability_zone": item.get("aws_availability_zone"),
                "aws_state": item.get("aws_state"),
                "aws_launch_time": item.get("aws_launch_time"),
                "aws_tags": tags,
                "last_discovered_at": now_iso,
                "status": status if matched_server.get("status") != "critical" else matched_server["status"],
            }
            if conn_id:
                payload["aws_connection_id"] = conn_id
            if item.get("ip_address") and item["ip_address"] != "auto-assigned":
                payload["ip_address"] = item["ip_address"]

            upsert_discovered_server(payload)
            updated_count += 1
        else:
            # Create new server entry
            payload = {
                "server_name": instance_name,
                "ip_address": item.get("ip_address"),
                "status": status,
                "specifications": item.get("specifications", {}),
                "source": "aws_discovery",
                "aws_instance_id": instance_id,
                "aws_region": item.get("aws_region"),
                "aws_availability_zone": item.get("aws_availability_zone"),
                "aws_state": item.get("aws_state"),
                "aws_launch_time": item.get("aws_launch_time"),
                "aws_tags": tags,
                "cost_tag": tags.get(AWS_COST_TAG_KEY) or instance_name,
                "last_discovered_at": now_iso,
            }
            if conn_id:
                payload["aws_connection_id"] = conn_id
            upsert_discovered_server(payload)
            created_count += 1

    return DiscoveryResult(
        discovered_count=len(instances),
        created_count=created_count,
        updated_count=updated_count,
        matched_count=matched_count,
        instances=instances,
        region=effective_region,
    )
