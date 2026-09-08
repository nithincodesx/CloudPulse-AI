"""AWS Resource Discovery Service for CloudPulse AI.

Provides modular discovery of AWS infrastructure (EC2, RDS, ECS, Lambda, EBS, ELB) and
integrates discovered instances idempotently into the CloudPulse server inventory model.

Supports Multi-Tenant cross-account AssumeRole connections as well as
local developer .env fallback.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

from dotenv import load_dotenv

from aws_credentials import extract_account_id_from_arn, get_aws_client
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


# ---------------------------------------------------------------------------
# Modular Resource Discoverer Base Class & Registry
# ---------------------------------------------------------------------------

class ResourceDiscoverer(ABC):
    """Abstract base class for AWS resource discovery providers."""

    service_name: str = "base"

    def __init__(
        self,
        region: str | None = None,
        connection: Optional[dict[str, Any]] = None,
    ) -> None:
        self.connection = connection
        self.region = region or (connection.get("region") if connection else None) or AWS_REGION
        self.account_id = (
            (connection.get("aws_account_id") or extract_account_id_from_arn(connection.get("role_arn", "")))
            if connection else None
        ) or "unknown-account" 
        self.org_id = connection.get("organization_id") if connection else None
        self.conn_id = connection.get("id") if connection else None

    @abstractmethod
    def discover(self, region: str | None = None) -> list[dict[str, Any]]:
        """Discover resources and return normalized metadata dictionaries."""
        pass


class DiscoveryRegistry:
    """Registry for pluggable AWS resource discoverers."""

    _registry: Dict[str, Type[ResourceDiscoverer]] = {}

    @classmethod
    def register(cls, name: str, discoverer_cls: Type[ResourceDiscoverer]) -> None:
        cls._registry[name] = discoverer_cls

    @classmethod
    def get(cls, name: str) -> Optional[Type[ResourceDiscoverer]]:
        return cls._registry.get(name)

    @classmethod
    def list_services(cls) -> List[str]:
        return list(cls._registry.keys())


# ---------------------------------------------------------------------------
# EC2 Resource Discoverer
# ---------------------------------------------------------------------------

class EC2Discoverer(ResourceDiscoverer):
    """AWS EC2 instance discovery provider."""

    service_name: str = "ec2"

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
        logger.info("aws.discovery.ec2.start", region=self.region, account_id=self.account_id)

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
                    owner_id = reservation.get("OwnerId") or self.account_id
                    for instance in reservation.get("Instances", []):
                        parsed = self._parse_instance(instance, owner_account_id=owner_id)
                        if parsed:
                            discovered_instances.append(parsed)

            logger.info(
                "aws.discovery.ec2.success",
                count=len(discovered_instances),
                region=self.region,
            )
            return discovered_instances

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
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

    def _parse_instance(self, instance: dict[str, Any], owner_account_id: str | None = None) -> dict[str, Any]:
        """Normalize EC2 raw describe_instances item into CloudPulse metadata schema.
        
        Collects:
        - instance ID (aws_instance_id / aws_resource_id)
        - name (server_name)
        - instance type (specifications.type)
        - region (aws_region)
        - availability zone (aws_availability_zone)
        - state (aws_state)
        - private IP (private_ip)
        - public IP (public_ip)
        - launch time (aws_launch_time)
        - tags (aws_tags)
        - account ID (aws_account_id)
        - organization ID (organization_id)
        - AWS connection ID (aws_connection_id)
        - AWS resource ID (aws_resource_id)
        """
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

        # IP addresses (collected as network metadata, NOT used as primary identity)
        private_ip = instance.get("PrivateIpAddress") or ""
        public_ip = instance.get("PublicIpAddress") or ""
        display_ip = public_ip or private_ip or "auto-assigned"

        architecture = instance.get("Architecture", "x86_64")
        hypervisor = instance.get("Hypervisor", "xen")

        # Derive approximate vcpus and ram_gb
        vcpus, ram_gb = _approximate_instance_specs(instance_type)

        specifications = {
            "type": instance_type,
            "architecture": architecture,
            "hypervisor": hypervisor,
            "vcpus": vcpus,
            "ram_gb": ram_gb,
        }

        account_id = owner_account_id or self.account_id

        return {
            "aws_instance_id": instance_id,
            "aws_resource_id": instance_id,
            "server_name": name,
            "resource_type": "ec2",
            "ip_address": display_ip,
            "private_ip": private_ip,
            "public_ip": public_ip,
            "aws_region": self.region,
            "aws_availability_zone": az,
            "aws_state": state_name,
            "aws_launch_time": launch_time_str,
            "aws_tags": tags,
            "aws_account_id": account_id,
            "organization_id": self.org_id,
            "aws_connection_id": self.conn_id,
            "specifications": specifications,
        }


# ---------------------------------------------------------------------------
# Extensible Discovery Providers (RDS, ECS, Lambda, EBS, ELB)
# ---------------------------------------------------------------------------

class RDSDiscoverer(ResourceDiscoverer):
    """AWS Relational Database Service (RDS) discovery provider."""
    service_name: str = "rds"

    def discover(self, region: str | None = None) -> list[dict[str, Any]]:
        if region:
            self.region = region
        client = get_aws_client("rds", connection=self.connection, region=self.region)
        try:
            paginator = client.get_paginator("describe_db_instances")
            instances = []
            for page in paginator.paginate():
                for db in page.get("DBInstances", []):
                    db_id = db.get("DBInstanceIdentifier", "")
                    instances.append({
                        "aws_resource_id": db.get("DBInstanceArn", db_id),
                        "server_name": db_id,
                        "resource_type": "rds",
                        "aws_region": self.region,
                        "aws_state": db.get("DBInstanceStatus", "available"),
                        "aws_account_id": self.account_id,
                        "specifications": {
                            "type": db.get("DBInstanceClass", "db.t3.medium"),
                            "engine": db.get("Engine", "postgres"),
                            "allocated_storage": db.get("AllocatedStorage", 20),
                        },
                    })
            return instances
        except Exception as exc:
            logger.warning("aws.discovery.rds.skipped", error=str(exc))
            return []


class ECSDiscoverer(ResourceDiscoverer):
    """AWS Elastic Container Service (ECS) discovery provider."""
    service_name: str = "ecs"

    def discover(self, region: str | None = None) -> list[dict[str, Any]]:
        if region:
            self.region = region
        client = get_aws_client("ecs", connection=self.connection, region=self.region)
        try:
            clusters = client.list_clusters().get("clusterArns", [])
            return [
                {
                    "aws_resource_id": arn,
                    "server_name": arn.split("/")[-1],
                    "resource_type": "ecs_cluster",
                    "aws_region": self.region,
                    "aws_account_id": self.account_id,
                }
                for arn in clusters
            ]
        except Exception as exc:
            logger.warning("aws.discovery.ecs.skipped", error=str(exc))
            return []


class LambdaDiscoverer(ResourceDiscoverer):
    """AWS Lambda serverless function discovery provider."""
    service_name: str = "lambda"

    def discover(self, region: str | None = None) -> list[dict[str, Any]]:
        if region:
            self.region = region
        client = get_aws_client("lambda", connection=self.connection, region=self.region)
        try:
            paginator = client.get_paginator("list_functions")
            functions = []
            for page in paginator.paginate():
                for fn in page.get("Functions", []):
                    functions.append({
                        "aws_resource_id": fn.get("FunctionArn"),
                        "server_name": fn.get("FunctionName"),
                        "resource_type": "lambda",
                        "aws_region": self.region,
                        "aws_account_id": self.account_id,
                        "specifications": {
                            "runtime": fn.get("Runtime"),
                            "memory_size": fn.get("MemorySize"),
                            "timeout": fn.get("Timeout"),
                        },
                    })
            return functions
        except Exception as exc:
            logger.warning("aws.discovery.lambda.skipped", error=str(exc))
            return []


class EBSDiscoverer(ResourceDiscoverer):
    """AWS Elastic Block Store (EBS) discovery provider."""
    service_name: str = "ebs"

    def discover(self, region: str | None = None) -> list[dict[str, Any]]:
        if region:
            self.region = region
        client = get_aws_client("ec2", connection=self.connection, region=self.region)
        try:
            paginator = client.get_paginator("describe_volumes")
            volumes = []
            for page in paginator.paginate():
                for vol in page.get("Volumes", []):
                    vol_id = vol.get("VolumeId")
                    volumes.append({
                        "aws_resource_id": vol_id,
                        "server_name": vol_id,
                        "resource_type": "ebs_volume",
                        "aws_region": self.region,
                        "aws_state": vol.get("State"),
                        "aws_account_id": self.account_id,
                        "specifications": {
                            "size_gb": vol.get("Size"),
                            "volume_type": vol.get("VolumeType"),
                            "iops": vol.get("Iops"),
                        },
                    })
            return volumes
        except Exception as exc:
            logger.warning("aws.discovery.ebs.skipped", error=str(exc))
            return []


class ELBDiscoverer(ResourceDiscoverer):
    """AWS Elastic Load Balancer (ELB / ALB / NLB) discovery provider."""
    service_name: str = "elbv2"

    def discover(self, region: str | None = None) -> list[dict[str, Any]]:
        if region:
            self.region = region
        client = get_aws_client("elbv2", connection=self.connection, region=self.region)
        try:
            paginator = client.get_paginator("describe_load_balancers")
            lbs = []
            for page in paginator.paginate():
                for lb in page.get("LoadBalancers", []):
                    lbs.append({
                        "aws_resource_id": lb.get("LoadBalancerArn"),
                        "server_name": lb.get("LoadBalancerName"),
                        "resource_type": "elb",
                        "aws_region": self.region,
                        "aws_state": lb.get("State", {}).get("Code", "active"),
                        "aws_account_id": self.account_id,
                        "specifications": {
                            "type": lb.get("Type"),
                            "scheme": lb.get("Scheme"),
                            "dns_name": lb.get("DNSName"),
                        },
                    })
            return lbs
        except Exception as exc:
            logger.warning("aws.discovery.elbv2.skipped", error=str(exc))
            return []


# Register providers in the global registry
DiscoveryRegistry.register("ec2", EC2Discoverer)
DiscoveryRegistry.register("rds", RDSDiscoverer)
DiscoveryRegistry.register("ecs", ECSDiscoverer)
DiscoveryRegistry.register("lambda", LambdaDiscoverer)
DiscoveryRegistry.register("ebs", EBSDiscoverer)
DiscoveryRegistry.register("elbv2", ELBDiscoverer)


# ---------------------------------------------------------------------------
# Helper Heuristics & Sizing
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Resource Matching & Idempotent Synchronization Pipeline
# ---------------------------------------------------------------------------

def match_discovered_resource_to_telemetry_node(
    item: dict[str, Any],
    existing_servers: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Match an AWS discovered resource to an existing CloudPulse telemetry node.
    
    HIERARCHY OF RELIABLE IDENTIFIERS:
    1. AWS Instance ID / AWS Resource ID (exact, unique match)
    2. AWS Account ID + Region + Explicit Tag/Node metadata (e.g. `cloudpulse:id`, `node_id`, `server`, `Name`)
    3. Server name / cost tag exact match within same organization/account
    
    * IP address is NEVER used as the primary identity because cloud IPs change dynamically.
    """
    instance_id = item.get("aws_instance_id") or item.get("aws_resource_id")
    account_id = item.get("aws_account_id")
    region = item.get("aws_region")
    tags = item.get("aws_tags", {})
    name = item.get("server_name", "")

    # Priority 1: Exact AWS Instance ID / AWS Resource ID match
    if instance_id:
        for s in existing_servers:
            if s.get("aws_instance_id") == instance_id or s.get("aws_resource_id") == instance_id:
                return s

    # Priority 2: Dedicated CloudPulse node tag match (e.g. `cloudpulse:id`, `cloudpulse-node`, `node_id`)
    cloudpulse_tag = tags.get("cloudpulse:id") or tags.get("node_id") or tags.get("cloudpulse-node")
    if cloudpulse_tag:
        want_tag = cloudpulse_tag.strip().lower()
        for s in existing_servers:
            if str(s.get("id", "")).lower() == want_tag or (s.get("server_name") or "").strip().lower() == want_tag:
                return s

    # Priority 3: AWS Account ID + Region + Cost Tag / Name match
    cost_tag_val = tags.get(AWS_COST_TAG_KEY) or tags.get("server") or tags.get("Server") or name
    if cost_tag_val:
        want_val = cost_tag_val.strip().lower()
        for s in existing_servers:
            s_cost_tag = (s.get("cost_tag") or "").strip().lower()
            s_name = (s.get("server_name") or "").strip().lower()
            
            # Account / region affinity check if available
            s_acc = s.get("aws_account_id")
            s_reg = s.get("aws_region")
            if s_acc and account_id and s_acc != account_id:
                continue
            if s_reg and region and s_reg != region:
                continue

            if s_cost_tag and s_cost_tag == want_val:
                return s
            if s_name and s_name == want_val:
                return s

    return None


def sync_aws_resources(
    region: str | None = None,
    connection: Optional[dict[str, Any]] = None,
) -> DiscoveryResult:
    """Run AWS discovery across services and upsert servers idempotently into the database.
    
    Guarantees:
    - Never creates duplicate server records.
    - Captures all 11 EC2 metadata fields.
    - Associates with organization_id and aws_connection_id.
    - Idempotent upsert behavior.
    """
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
    org_id = connection.get("organization_id") if connection else None
    account_id = (
        (connection.get("aws_account_id") or extract_account_id_from_arn(connection.get("role_arn", "")))
        if connection else None
    )

    for item in instances:
        instance_id = item["aws_instance_id"]
        instance_name = item["server_name"]
        tags = item.get("aws_tags", {})

        # Reliable identifier hierarchical matching
        matched_server = match_discovered_resource_to_telemetry_node(item, existing_servers)

        status = _map_aws_state_to_status(item.get("aws_state", "running"))

        if matched_server:
            matched_count += 1
            # Update existing server record idempotently
            payload = {
                "id": matched_server["id"],
                "server_name": matched_server.get("server_name") or instance_name,
                "source": "aws_discovery",
                "resource_type": "ec2",
                "aws_instance_id": instance_id,
                "aws_resource_id": instance_id,
                "aws_region": item.get("aws_region"),
                "aws_availability_zone": item.get("aws_availability_zone"),
                "aws_state": item.get("aws_state"),
                "aws_launch_time": item.get("aws_launch_time"),
                "aws_tags": tags,
                "aws_account_id": item.get("aws_account_id") or account_id,
                "last_discovered_at": now_iso,
                "status": status if matched_server.get("status") != "critical" else matched_server["status"],
            }
            if org_id:
                payload["organization_id"] = org_id
            if conn_id:
                payload["aws_connection_id"] = conn_id
            if item.get("private_ip"):
                payload["private_ip"] = item["private_ip"]
            if item.get("public_ip"):
                payload["public_ip"] = item["public_ip"]
            if item.get("ip_address") and item["ip_address"] != "auto-assigned":
                payload["ip_address"] = item["ip_address"]

            upsert_discovered_server(payload)
            updated_count += 1
        else:
            # Create new server entry
            payload = {
                "server_name": instance_name,
                "ip_address": item.get("ip_address"),
                "private_ip": item.get("private_ip"),
                "public_ip": item.get("public_ip"),
                "resource_type": "ec2",
                "status": status,
                "specifications": item.get("specifications", {}),
                "source": "aws_discovery",
                "aws_instance_id": instance_id,
                "aws_resource_id": instance_id,
                "aws_region": item.get("aws_region"),
                "aws_availability_zone": item.get("aws_availability_zone"),
                "aws_state": item.get("aws_state"),
                "aws_launch_time": item.get("aws_launch_time"),
                "aws_tags": tags,
                "aws_account_id": item.get("aws_account_id") or account_id,
                "cost_tag": tags.get(AWS_COST_TAG_KEY) or instance_name,
                "last_discovered_at": now_iso,
            }
            if org_id:
                payload["organization_id"] = org_id
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
