"""Unit tests for Multi-Tenant SaaS AWS Connection System.

Tests ExternalId security, Role ARN validation, IAM policy generators,
STS AssumeRole credential caching, and connection verification with mocked AWS APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError

from aws_credentials import (
    AWSCredentialSessionCache,
    extract_account_id_from_arn,
    generate_cloudformation_quick_launch_url,
    generate_cloudformation_template,
    generate_external_id,
    generate_iam_permissions_policy,
    generate_iam_trust_policy,
    get_aws_client,
    get_cloudpulse_account_id,
    validate_role_arn,
)
from aws_service import (
    verify_connection_credentials,
)


def test_external_id_generation_is_secure_and_unique():
    id1 = generate_external_id()
    id2 = generate_external_id()

    assert id1.startswith("cloudpulse_")
    assert id2.startswith("cloudpulse_")
    assert id1 != id2
    assert len(id1) >= 32  # Minimum 128-bit entropy


def test_role_arn_validation():
    # Valid ARNs
    assert validate_role_arn("arn:aws:iam::123456789012:role/CloudPulseReadOnlyRole")
    assert validate_role_arn("arn:aws:iam::987654321098:role/service-roles/MyRole_v1")

    # Invalid ARNs
    assert not validate_role_arn("invalid:arn")
    assert not validate_role_arn("arn:aws:iam::123:role/ShortAccount")
    assert not validate_role_arn("arn:aws:s3:::my-bucket")
    assert not validate_role_arn("")


def test_extract_account_id_from_arn():
    assert extract_account_id_from_arn("arn:aws:iam::123456789012:role/CloudPulseRole") == "123456789012"
    assert extract_account_id_from_arn("invalid-arn") is None


def test_iam_trust_policy_generator():
    ext_id = "cloudpulse_abc123"
    policy = generate_iam_trust_policy(ext_id, cloudpulse_account_id="999888777666")

    assert policy["Version"] == "2012-10-17"
    statement = policy["Statement"][0]
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == "sts:AssumeRole"
    assert statement["Principal"]["AWS"] == "arn:aws:iam::999888777666:root"
    assert statement["Condition"]["StringEquals"]["sts:ExternalId"] == ext_id


def test_iam_permissions_policy_is_least_privilege():
    policy = generate_iam_permissions_policy()
    actions = []
    for stmt in policy["Statement"]:
        assert stmt["Effect"] == "Allow"
        actions.extend(stmt["Action"])

    # Must contain read-only actions
    assert "ec2:DescribeInstances" in actions
    assert "ce:GetCostAndUsage" in actions

    # Must NEVER contain write / modify / delete actions
    assert "ec2:RunInstances" not in actions
    assert "ec2:TerminateInstances" not in actions
    assert "ec2:StopInstances" not in actions
    assert "iam:CreateUser" not in actions


def test_cloudformation_template_and_url_generator():
    ext_id = "cloudpulse_test_cf"
    template = generate_cloudformation_template(ext_id, cloudpulse_account_id="111222333444")

    assert "CloudPulseReadOnlyRole" in template["Resources"]
    role_props = template["Resources"]["CloudPulseReadOnlyRole"]["Properties"]
    assert role_props["RoleName"] == "CloudPulseReadOnlyRole"

    url = generate_cloudformation_quick_launch_url(ext_id, region="us-west-2", cloudpulse_account_id="111222333444")
    assert "console.aws.amazon.com/cloudformation" in url
    assert "region=us-west-2" in url
    assert "CloudPulse-Monitoring-Integration" in url


@patch("aws_credentials.boto3.client")
def test_session_cache_assume_role_success(mock_boto_client):
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "ASIA_TEST_KEY",
            "SecretAccessKey": "SECRET_TEST_KEY",
            "SessionToken": "TOKEN_TEST",
            "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
        }
    }
    mock_boto_client.return_value = mock_sts

    cache = AWSCredentialSessionCache()
    role_arn = "arn:aws:iam::123456789012:role/CloudPulseRole"
    ext_id = "cloudpulse_test_ext"

    # First call calls STS assume_role
    session1 = cache.get_session(role_arn, ext_id, region="us-east-1")
    assert mock_sts.assume_role.call_count == 1

    # Second call should reuse cached session without calling STS again
    session2 = cache.get_session(role_arn, ext_id, region="us-east-1")
    assert mock_sts.assume_role.call_count == 1
    assert session1 == session2


@patch("aws_service.get_aws_client")
def test_verify_connection_credentials_success(mock_get_client):
    mock_sts = MagicMock()
    mock_sts.get_caller_identity.return_value = {"Account": "123456789012", "Arn": "arn:aws:sts::123456789012:assumed-role/..."}

    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {"Reservations": []}

    def client_router(service, **kwargs):
        if service == "sts":
            return mock_sts
        elif service == "ec2":
            return mock_ec2
        return MagicMock()

    mock_get_client.side_effect = client_router

    conn = {
        "id": "conn-001",
        "role_arn": "arn:aws:iam::123456789012:role/CloudPulseReadOnlyRole",
        "external_id": "cloudpulse_valid_ext",
        "region": "us-east-1",
    }

    success, account_id, err = verify_connection_credentials(conn)
    assert success is True
    assert account_id == "123456789012"
    assert err is None


@patch("aws_service.get_aws_client")
def test_verify_connection_credentials_access_denied(mock_get_client):
    error_response = {
        "Error": {
            "Code": "AccessDenied",
            "Message": "User is not authorized to perform: sts:AssumeRole on resource.",
        }
    }
    mock_sts = MagicMock()
    mock_sts.get_caller_identity.side_effect = ClientError(error_response, "AssumeRole")
    mock_get_client.return_value = mock_sts

    conn = {
        "id": "conn-002",
        "role_arn": "arn:aws:iam::123456789012:role/CloudPulseReadOnlyRole",
        "external_id": "cloudpulse_wrong_ext",
        "region": "us-east-1",
    }

    success, account_id, err = verify_connection_credentials(conn)
    assert success is False
    assert account_id is None
    assert "Access Denied" in err
    assert "Trust Policy" in err


def test_verify_connection_credentials_invalid_arn():
    conn = {
        "id": "conn-003",
        "role_arn": "invalid-arn",
        "external_id": "cloudpulse_test",
    }
    success, account_id, err = verify_connection_credentials(conn)
    assert success is False
    assert "Invalid IAM Role ARN format" in err
