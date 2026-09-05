"""CloudPulse AI — Multi-Tenant AWS Connection Service & Verification.

Handles onboarding, STS AssumeRole verification, multi-account sync, and audit logging.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from aws_credentials import (
    extract_account_id_from_arn,
    get_aws_client,
    validate_role_arn,
)
from database import (
    create_aws_connection,
    get_aws_connection,
    list_aws_connections,
    update_aws_connection,
)
from logging_conf import get_logger

logger = get_logger("backend.aws_service")


def verify_connection_credentials(connection: dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
    """Test AssumeRole, CallerIdentity, and read-only permissions for an AWS connection.

    Returns:
        (success: bool, detected_account_id: Optional[str], error_message: Optional[str])
    """
    role_arn = connection.get("role_arn", "").strip()
    external_id = connection.get("external_id", "").strip()
    region = connection.get("region", "us-east-1").strip()

    if not validate_role_arn(role_arn):
        return False, None, f"Invalid IAM Role ARN format: '{role_arn}'. Expected format: arn:aws:iam::123456789012:role/RoleName"

    if not external_id:
        return False, None, "Connection is missing required ExternalId for AssumeRole authentication."

    try:
        # 1. Attempt STS AssumeRole & GetCallerIdentity
        sts_client = get_aws_client("sts", connection=connection, region=region)
        caller_identity = sts_client.get_caller_identity()
        detected_account_id = caller_identity.get("Account")

        # 2. Test EC2 read permissions
        ec2_client = get_aws_client("ec2", connection=connection, region=region)
        ec2_client.describe_instances(MaxResults=5)

        logger.info(
            "aws.connection.verified",
            connection_id=connection.get("id"),
            account_id=detected_account_id,
            role_arn=role_arn,
        )
        return True, detected_account_id, None

    except Exception as exc:
        err_msg = str(exc)
        logger.warning(
            "aws.connection.verify_failed",
            connection_id=connection.get("id"),
            role_arn=role_arn,
            error=err_msg,
        )
        # Produce clean, user-friendly error diagnostics
        if "AccessDenied" in err_msg or "not authorized to perform: sts:AssumeRole" in err_msg:
            friendly_err = (
                "Access Denied: CloudPulse is not authorized to assume this IAM Role. "
                "Please verify the Trust Policy in your AWS account includes CloudPulse's Account ID and your unique ExternalId."
            )
        elif "InvalidParameterValue" in err_msg:
            friendly_err = f"Invalid parameter during AWS connection verification: {err_msg}"
        else:
            friendly_err = f"Verification failed: {err_msg}"

        return False, None, friendly_err


def verify_and_save_connection(connection_id: str, user_id: Optional[str] = None) -> dict[str, Any]:
    """Verify an existing connection and update its status in Supabase."""
    conn = get_aws_connection(connection_id, user_id=user_id)
    if not conn:
        raise ValueError(f"AWS connection {connection_id} not found")

    success, detected_account, error_msg = verify_connection_credentials(conn)
    now_iso = datetime.now(timezone.utc).isoformat()

    updates: dict[str, Any] = {
        "status": "connected" if success else "error",
        "error_message": None if success else error_msg,
        "last_verified_at": now_iso,
        "updated_at": now_iso,
    }

    if success and detected_account:
        updates["aws_account_id"] = detected_account
    elif not conn.get("aws_account_id") and conn.get("role_arn"):
        extracted = extract_account_id_from_arn(conn["role_arn"])
        if extracted:
            updates["aws_account_id"] = extracted

    updated = update_aws_connection(connection_id, updates)
    return updated or {**conn, **updates}
