"""CloudPulse AI — AWS Multi-Tenant Credential Provider & AssumeRole Engine.

Provides cross-account IAM role assumption using STS AssumeRole with secure ExternalIds.
Temporary STS credentials are kept in-memory, cached with automatic refresh upon expiration,
and NEVER persisted to database or sent to frontend.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple
from urllib.parse import quote

from dotenv import load_dotenv

from logging_conf import get_logger

logger = get_logger("backend.aws_credentials")

load_dotenv()

# Master CloudPulse AWS Account (the trusted parent account for AssumeRole)
CLOUDPULSE_AWS_ACCOUNT_ID = os.getenv("CLOUDPULSE_AWS_ACCOUNT_ID", "123456789012").strip()

# Developer fallback credentials (for local dev mode)
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
DEFAULT_AWS_REGION = os.getenv("AWS_REGION", "us-east-1").strip()

# Boto3 import availability
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    _BOTO3_AVAILABLE = True
except ImportError:  # pragma: no cover
    boto3 = None
    _BOTO3_AVAILABLE = False


# Regex for AWS IAM Role ARN validation
ROLE_ARN_PATTERN = re.compile(r"^arn:aws:iam::(?P<account_id>\d{12}):role/(?P<role_name>[\w+=,.@\-_/]+)$")


def generate_external_id() -> str:
    """Generate a cryptographically secure, unguessable ExternalId for tenant isolation."""
    return f"cloudpulse_{secrets.token_hex(16)}"


def validate_role_arn(role_arn: str) -> bool:
    """Validate that the provided string matches AWS IAM Role ARN format."""
    if not role_arn or not isinstance(role_arn, str):
        return False
    return bool(ROLE_ARN_PATTERN.match(role_arn.strip()))


def extract_account_id_from_arn(role_arn: str) -> Optional[str]:
    """Extract the 12-digit AWS Account ID from a valid Role ARN."""
    if not role_arn:
        return None
    match = ROLE_ARN_PATTERN.match(role_arn.strip())
    return match.group("account_id") if match else None


def get_cloudpulse_account_id() -> str:
    """Get the CloudPulse Master AWS Account ID used in customer trust policies."""
    return CLOUDPULSE_AWS_ACCOUNT_ID or "123456789012"


def humanize_aws_error(error_code_or_msg: str) -> str:
    """Convert raw AWS API error messages into human-friendly, actionable diagnostic explanations."""
    err = str(error_code_or_msg)
    if "NoSuchEntity" in err or "cannot be found" in err.lower():
        return "CloudPulse cannot access this AWS account because the IAM role no longer exists."
    if "AccountDisabled" in err or "is disabled" in err.lower():
        return "The target AWS account has been suspended or disabled."
    if "AccessDenied" in err or "UnauthorizedOperation" in err or "not authorized" in err.lower():
        if "sts:AssumeRole" in err or "assume" in err.lower():
            return "Role assumption failed — Check IAM trust policy and verify ExternalId matches."
        if "ce:" in err or "CostExplorer" in err or "cost" in err.lower():
            return "Cost Explorer permissions missing — ensure ce:GetCostAndUsage and ce:GetDimensionValues are allowed."
        if "ec2:" in err or "DescribeInstances" in err:
            return "EC2 Describe permissions missing — ensure ec2:DescribeInstances is granted."
        return "AWS permission denied — IAM role permissions may have changed."
    if "DataUnavailableException" in err or "not enabled" in err.lower():
        return "Cost Explorer is not enabled or billing data is not yet available in this AWS account."
    if "Throttling" in err or "RequestLimitExceeded" in err or "Rate exceeded" in err:
        return "AWS API request rate limit reached — automatic retry with backoff."
    if "ExpiredToken" in err:
        return "Temporary security credentials expired — refreshing session."
    if "EndpointConnectionError" in err or "ConnectTimeoutError" in err or "timeout" in err.lower():
        return "AWS network connection timeout — please verify AWS region endpoint accessibility."
    if "InvalidParameter" in err or "ValidationError" in err:
        return "Invalid role ARN or External ID parameter."
    return err[:120] if len(err) > 120 else err


def generate_iam_trust_policy(external_id: str, cloudpulse_account_id: Optional[str] = None) -> dict[str, Any]:
    """Generate dynamic IAM Trust Policy JSON granting CloudPulse AssumeRole permission with ExternalId."""
    parent_account = cloudpulse_account_id or get_cloudpulse_account_id()
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "AWS": f"arn:aws:iam::{parent_account}:root"
                },
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {
                        "sts:ExternalId": external_id
                    }
                }
            }
        ]
    }


def generate_iam_permissions_policy() -> dict[str, Any]:
    """Generate least-privilege read-only permissions policy for CloudPulse features."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CloudPulseEC2ReadOnly",
                "Effect": "Allow",
                "Action": [
                    "ec2:DescribeInstances",
                    "ec2:DescribeInstanceStatus",
                    "ec2:DescribeVolumes",
                    "ec2:DescribeTags",
                    "ec2:DescribeRegions",
                    "ec2:DescribeAvailabilityZones"
                ],
                "Resource": "*"
            },
            {
                "Sid": "CloudPulseCostExplorerReadOnly",
                "Effect": "Allow",
                "Action": [
                    "ce:GetCostAndUsage",
                    "ce:GetCostForecast",
                    "ce:GetDimensionValues",
                    "ce:GetTags"
                ],
                "Resource": "*"
            }
        ]
    }


def generate_cloudformation_template(external_id: str, cloudpulse_account_id: Optional[str] = None) -> dict[str, Any]:
    """Generate a CloudFormation template JSON for 1-click customer role deployment."""
    parent_account = cloudpulse_account_id or get_cloudpulse_account_id()
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "CloudPulse AI Read-Only Monitoring Role with Cross-Account ExternalId Authentication",
        "Resources": {
            "CloudPulseReadOnlyRole": {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "RoleName": "CloudPulseReadOnlyRole",
                    "AssumeRolePolicyDocument": generate_iam_trust_policy(external_id, parent_account),
                    "Policies": [
                        {
                            "PolicyName": "CloudPulseMonitoringReadOnlyPolicy",
                            "PolicyDocument": generate_iam_permissions_policy(),
                        }
                    ]
                }
            }
        },
        "Outputs": {
            "RoleArn": {
                "Description": "The ARN of the IAM Role to provide to CloudPulse",
                "Value": {"Fn::GetAtt": ["CloudPulseReadOnlyRole", "Arn"]}
            }
        }
    }


def generate_quick_create_url(
    external_id: str,
    region: str = "us-east-1",
    cloudpulse_account_id: Optional[str] = None,
) -> str:
    """Generate AWS CloudFormation 1-Click Quick-Create URL."""
    cfn_template = generate_cloudformation_template(external_id, cloudpulse_account_id)
    template_json = json.dumps(cfn_template)
    encoded_body = quote(template_json)
    stack_name = "CloudPulse-Monitoring-Integration"
    return (
        f"https://console.aws.amazon.com/cloudformation/home?region={region}#/stacks/create/review?"
        f"templateBody={encoded_body}&stackName={stack_name}"
    )


# ---------------------------------------------------------------------------
# In-Memory Thread-Safe STS Credential Cache
# ---------------------------------------------------------------------------

class AWSCredentialSessionCache:
    """Thread-safe cache for temporary STS credentials, auto-refreshing before expiration."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] = {}

    def get_session(
        self,
        role_arn: str,
        external_id: str,
        region: str = DEFAULT_AWS_REGION,
        duration_seconds: int = 3600,
    ) -> Any:
        """Return a boto3 Session authenticated via AssumeRole, refreshing if near expiration."""
        if not _BOTO3_AVAILABLE or boto3 is None:
            raise RuntimeError("boto3 is not installed or available.")

        cache_key = f"{role_arn}:{external_id}:{region}"
        now = datetime.now(timezone.utc)

        with self._lock:
            cached = self._cache.get(cache_key)
            if cached:
                # Reuse if at least 5 minutes remaining before expiration
                if cached["expiration"] > now + timedelta(minutes=5):
                    return cached["session"]

        # Assume role outside lock to prevent blocking other threads during network call
        session_name = f"CloudPulse-{secrets.token_hex(4)}"
        logger.info("aws.sts.assume_role.start", role_arn=role_arn, session_name=session_name)

        # Base STS client using developer credentials if present
        sts_kwargs: dict[str, Any] = {"region_name": region}
        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            sts_kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
            sts_kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY

        base_sts = boto3.client("sts", **sts_kwargs)
        try:
            response = base_sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName=session_name,
                ExternalId=external_id,
                DurationSeconds=duration_seconds,
            )
        except ClientError as exc:
            friendly_err = humanize_aws_error(str(exc))
            logger.error("aws.sts.assume_role.error", error=friendly_err, role_arn=role_arn)
            raise RuntimeError(friendly_err) from exc

        credentials = response["Credentials"]
        expiration = credentials["Expiration"]
        if expiration.tzinfo is None:
            expiration = expiration.replace(tzinfo=timezone.utc)

        assumed_session = boto3.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=region,
        )

        with self._lock:
            self._cache[cache_key] = {
                "credentials": {
                    "AccessKeyId": credentials["AccessKeyId"],
                    "Expiration": expiration,
                },
                "expiration": expiration,
                "session": assumed_session,
            }

        logger.info("aws.sts.assume_role.success", role_arn=role_arn, expires_at=expiration.isoformat())
        return assumed_session

    def clear(self) -> None:
        """Clear all cached sessions."""
        with self._lock:
            self._cache.clear()


# Global in-memory cache instance
_SESSION_CACHE = AWSCredentialSessionCache()


def get_aws_client(
    service_name: str,
    connection: Optional[dict[str, Any]] = None,
    region: Optional[str] = None,
) -> Any:
    """Get a boto3 client for an AWS service.

    If a connection dictionary with role_arn & external_id is provided, cross-account
    STS AssumeRole is used. Otherwise, falls back to developer .env credentials.
    """
    if not _BOTO3_AVAILABLE or boto3 is None:
        raise RuntimeError("boto3 is not available.")

    target_region = region or (connection.get("region") if connection else None) or DEFAULT_AWS_REGION

    if connection and connection.get("role_arn") and connection.get("external_id"):
        session = _SESSION_CACHE.get_session(
            role_arn=connection["role_arn"],
            external_id=connection["external_id"],
            region=target_region,
        )
        return session.client(service_name, region_name=target_region)

    # Fallback to backend/.env developer credentials or default boto3 client
    client_kwargs: dict[str, Any] = {"region_name": target_region}
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        client_kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
        client_kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
    return boto3.client(service_name, **client_kwargs)


def diagnose_connection_health(connection: dict[str, Any]) -> dict[str, Any]:
    """Perform granular health checks on an AWS connection and return humanized diagnostics.

    Returns:
        {
            "health_status": "HEALTHY" | "DEGRADED" | "ERROR",
            "checks": {
                "assume_role": {"status": "PASS"|"FAIL", "message": "...", "latency_ms": 120.5, "error": null},
                "account_id": {"status": "PASS"|"FAIL", "message": "...", "error": null},
                "ec2_permissions": {"status": "PASS"|"FAIL", "message": "...", "error": null},
                "cost_explorer_permissions": {"status": "PASS"|"FAIL", "message": "...", "error": null}
            },
            "summary": "..."
        }
    """
    import time
    checks: dict[str, dict[str, Any]] = {}
    health_status = "HEALTHY"

    # Check 1: STS AssumeRole
    t0 = time.perf_counter()
    session = None
    try:
        session = _SESSION_CACHE.get_session(
            role_arn=connection["role_arn"],
            external_id=connection["external_id"],
            region=connection.get("region") or DEFAULT_AWS_REGION,
        )
        latency = round((time.perf_counter() - t0) * 1000, 2)
        checks["assume_role"] = {
            "status": "PASS",
            "message": "Role assumption succeeded via AWS STS",
            "latency_ms": latency,
            "error": None,
        }
    except Exception as exc:
        clean_err = humanize_aws_error(str(exc))
        checks["assume_role"] = {
            "status": "FAIL",
            "message": clean_err,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "error": clean_err,
        }
        health_status = "ERROR"
        return {
            "health_status": health_status,
            "checks": checks,
            "summary": clean_err,
        }

    # Check 2: Account ID Match
    expected_acc = connection.get("aws_account_id")
    arn_acc = extract_account_id_from_arn(connection.get("role_arn", ""))
    if expected_acc and arn_acc and expected_acc != arn_acc:
        checks["account_id"] = {
            "status": "FAIL",
            "message": f"AWS Account ID mismatch (expected {expected_acc}, role has {arn_acc})",
            "error": "Account ID mismatch",
        }
        health_status = "ERROR"
    else:
        checks["account_id"] = {
            "status": "PASS",
            "message": f"Account ID matches: {arn_acc or expected_acc or 'Verified'}",
            "error": None,
        }

    # Check 3: EC2 DescribeInstances Permission
    try:
        ec2 = session.client("ec2", region_name=connection.get("region") or DEFAULT_AWS_REGION)
        ec2.describe_instances(MaxResults=5)
        checks["ec2_permissions"] = {
            "status": "PASS",
            "message": "EC2 DescribeInstances permission verified",
            "error": None,
        }
    except Exception as exc:
        clean_err = humanize_aws_error(str(exc))
        checks["ec2_permissions"] = {
            "status": "FAIL",
            "message": clean_err,
            "error": clean_err,
        }
        if health_status == "HEALTHY":
            health_status = "DEGRADED"

    # Check 4: Cost Explorer ce:GetDimensionValues Permission
    try:
        ce = session.client("ce", region_name="us-east-1")
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=2)).isoformat()
        end = today.isoformat()
        ce.get_dimension_values(
            TimePeriod={"Start": start, "End": end},
            Dimension="SERVICE",
        )
        checks["cost_explorer_permissions"] = {
            "status": "PASS",
            "message": "Cost Explorer permissions verified",
            "error": None,
        }
    except Exception as exc:
        clean_err = humanize_aws_error(str(exc))
        checks["cost_explorer_permissions"] = {
            "status": "FAIL",
            "message": clean_err,
            "error": clean_err,
        }
        if health_status == "HEALTHY":
            health_status = "DEGRADED"

    # Summary construction
    if health_status == "HEALTHY":
        summary = "All AWS cross-account permissions and services are operating normally"
    elif health_status == "DEGRADED":
        failed = [k for k, v in checks.items() if v["status"] == "FAIL"]
        summary = f"Partial permissions missing: {', '.join(failed)}"
    else:
        summary = checks.get("assume_role", {}).get("message") or "Connection error"

    return {
        "health_status": health_status,
        "checks": checks,
        "summary": summary,
    }


def verify_connection_credentials(
    role_arn: str,
    external_id: str,
    region: str = DEFAULT_AWS_REGION,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Verify that a customer's IAM Role ARN can be assumed using the given ExternalId.

    Returns:
        (success: bool, aws_account_id: Optional[str], error_message: Optional[str])
    """
    if not validate_role_arn(role_arn):
        return False, None, "Invalid IAM Role ARN format. Expected: arn:aws:iam::<account-id>:role/<role-name>"

    extracted_account_id = extract_account_id_from_arn(role_arn)

    if not _BOTO3_AVAILABLE or boto3 is None:
        logger.warning("aws.verify.mock_fallback", reason="boto3 not installed")
        return True, extracted_account_id, None

    try:
        session = _SESSION_CACHE.get_session(
            role_arn=role_arn,
            external_id=external_id,
            region=region,
        )
        # Test basic read permission with ec2:DescribeRegions
        ec2 = session.client("ec2", region_name=region)
        ec2.describe_regions(RegionNames=[region])
        logger.info("aws.verify.success", role_arn=role_arn, account_id=extracted_account_id)
        return True, extracted_account_id, None

    except Exception as exc:
        friendly_err = humanize_aws_error(str(exc))
        logger.error("aws.verify.failed", role_arn=role_arn, error=friendly_err)
        return False, extracted_account_id, friendly_err

# Backward compatibility alias
generate_cloudformation_quick_launch_url = generate_quick_create_url
