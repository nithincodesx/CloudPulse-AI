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


def test_humanize_aws_error_mappings():
    from aws_credentials import humanize_aws_error
    
    # Role deleted
    err_deleted = humanize_aws_error("ClientError: An error occurred (NoSuchEntity) when calling AssumeRole: The role cannot be found.")
    assert "no longer exists" in err_deleted

    # Account disabled
    err_disabled = humanize_aws_error("ClientError: An error occurred (AccountDisabledException): Account is disabled")
    assert "suspended or disabled" in err_disabled

    # Cost Explorer not enabled
    err_ce = humanize_aws_error("ClientError: (DataUnavailableException) Cost Explorer is not enabled")
    assert "Cost Explorer is not enabled" in err_ce

    # Throttling
    err_throttle = humanize_aws_error("ClientError: (ThrottlingException) Rate exceeded")
    assert "rate limit reached" in err_throttle

    # Expired token
    err_expired = humanize_aws_error("ClientError: (ExpiredToken) The security token included in the request is expired")
    assert "expired" in err_expired

    # Network timeout
    err_timeout = humanize_aws_error("EndpointConnectionError: Could not connect to the endpoint URL")
    assert "timeout" in err_timeout or "accessibility" in err_timeout


@patch("aws_credentials.boto3.client")
def test_session_cache_auto_refreshes_expired_credentials(mock_boto_client):
    mock_sts = MagicMock()
    # First call: expired in 2 minutes (less than 5 min threshold)
    mock_sts.assume_role.side_effect = [
        {
            "Credentials": {
                "AccessKeyId": "ASIA_EXPIRED_KEY",
                "SecretAccessKey": "SECRET_1",
                "SessionToken": "TOKEN_1",
                "Expiration": datetime.now(timezone.utc) + timedelta(minutes=2),
            }
        },
        {
            "Credentials": {
                "AccessKeyId": "ASIA_FRESH_KEY",
                "SecretAccessKey": "SECRET_2",
                "SessionToken": "TOKEN_2",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        }
    ]
    mock_boto_client.return_value = mock_sts

    cache = AWSCredentialSessionCache()
    role_arn = "arn:aws:iam::123456789012:role/CloudPulseRole"
    ext_id = "cloudpulse_refresh_test"

    # First fetch
    cache.get_session(role_arn, ext_id, region="us-east-1")
    assert mock_sts.assume_role.call_count == 1

    # Second fetch should trigger refresh because expiration was < 5 min
    cache.get_session(role_arn, ext_id, region="us-east-1")
    assert mock_sts.assume_role.call_count == 2


# ---------------------------------------------------------------------------
# NEW: Additional tests for Phase 2 requirements
# ---------------------------------------------------------------------------


def test_assume_role_uses_external_id():
    """Verify that AssumeRole always includes the ExternalId for tenant isolation."""
    from aws_credentials import _SESSION_CACHE

    with patch("aws_credentials.boto3.client") as mock_boto_client:
        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "ASIA_TEST",
                "SecretAccessKey": "SECRET",
                "SessionToken": "TOKEN",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        }
        mock_boto_client.return_value = mock_sts

        role_arn = "arn:aws:iam::123456789012:role/CloudPulseRole"
        ext_id = "cloudpulse_specific_external_id"

        _SESSION_CACHE.get_session(role_arn, ext_id, region="us-east-1")

        # Verify ExternalId was passed to AssumeRole
        call_kwargs = mock_sts.assume_role.call_args[1]
        assert call_kwargs["ExternalId"] == ext_id
        assert call_kwargs["RoleArn"] == role_arn


def test_assume_role_invalid_external_id_fails():
    """Verify that an invalid ExternalId causes AccessDenied."""
    with patch("aws_service.get_aws_client") as mock_get_client:
        mock_sts = MagicMock()
        error_response = {
            "Error": {
                "Code": "AccessDenied",
                "Message": "User is not authorized to perform: sts:AssumeRole on resource.",
            }
        }
        mock_sts.get_caller_identity.side_effect = ClientError(error_response, "AssumeRole")
        mock_get_client.return_value = mock_sts

        conn = {
            "id": "conn-invalid-ext",
            "role_arn": "arn:aws:iam::123456789012:role/CloudPulseRole",
            "external_id": "wrong_external_id",
            "region": "us-east-1",
        }

        success, account_id, err = verify_connection_credentials(conn)
        assert success is False
        assert "Access Denied" in err
        assert "ExternalId" in err or "Trust Policy" in err


def test_assume_role_invalid_role_arn_fails():
    """Verify that an invalid role ARN is rejected before calling AWS."""
    conn = {
        "id": "conn-invalid-arn",
        "role_arn": "not-an-arn",
        "external_id": "cloudpulse_test",
    }

    success, account_id, err = verify_connection_credentials(conn)
    assert success is False
    assert "Invalid IAM Role ARN format" in err


def test_no_long_lived_credentials_required():
    """Verify that the system never requires long-lived AWS access keys."""
    import inspect
    from aws_credentials import AWSCredentialSessionCache

    source = inspect.getsource(AWSCredentialSessionCache)
    # Should use STS AssumeRole, not access keys
    assert "assume_role" in source.lower() or "AssumeRole" in source


def test_multiple_aws_accounts_per_organization():
    """Verify that multiple AWS accounts can be connected to one organization."""
    from aws_credentials import AWSCredentialSessionCache

    with patch("aws_credentials.boto3.client") as mock_boto_client:
        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "ASIA_MULTI",
                "SecretAccessKey": "SECRET",
                "SessionToken": "TOKEN",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        }
        mock_boto_client.return_value = mock_sts

        cache = AWSCredentialSessionCache()

        # Simulate multiple AWS accounts
        accounts = [
            ("arn:aws:iam::111111111111:role/CloudPulseRole", "cloudpulse_ext_1"),
            ("arn:aws:iam::222222222222:role/CloudPulseRole", "cloudpulse_ext_2"),
            ("arn:aws:iam::333333333333:role/CloudPulseRole", "cloudpulse_ext_3"),
        ]

        sessions = []
        for role_arn, ext_id in accounts:
            session = cache.get_session(role_arn, ext_id, region="us-east-1")
            sessions.append(session)

        # Each account should have its own session
        assert len(sessions) == 3
        # STS should have been called 3 times (once per account)
        assert mock_sts.assume_role.call_count == 3


def test_credentials_never_exposed_in_logs():
    """Verify that AWS credentials are never logged."""
    import logging
    from io import StringIO

    # Capture log output
    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("aws_credentials")
    logger.addHandler(handler)

    with patch("aws_credentials.boto3.client") as mock_boto_client:
        mock_sts = MagicMock()
        mock_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "ASIA_SENSITIVE_KEY",
                "SecretAccessKey": "SUPER_SECRET_KEY_NEVER_LOGGED",
                "SessionToken": "TOKEN_SECRET",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        }
        mock_boto_client.return_value = mock_sts

        cache = AWSCredentialSessionCache()
        cache.get_session(
            "arn:aws:iam::123456789012:role/CloudPulseRole",
            "cloudpulse_test",
            region="us-east-1",
        )

    log_output = log_stream.getvalue()
    assert "SUPER_SECRET_KEY_NEVER_LOGGED" not in log_output
    assert "TOKEN_SECRET" not in log_output
    assert "ASIA_SENSITIVE_KEY" not in log_output

    logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# AUTHORIZATION & CROSS-TENANT ISOLATION TESTS
# ---------------------------------------------------------------------------


class TestAuthorizationAndCrossTenantIsolation:
    """Test that all endpoints enforce JWT-derived identity and prevent cross-tenant access."""

    def _make_user(self, user_id="user-1", email="user1@test.com"):
        from auth import AuthenticatedUser
        return AuthenticatedUser(user_id=user_id, email=email, role="authenticated")

    def test_list_connections_uses_jwt_identity(self):
        """Verify list connections uses JWT-derived org, not client-provided org_id."""
        from fastapi.testclient import TestClient
        from main import app, get_current_user
        from auth import AuthenticatedUser

        user = self._make_user()

        async def _fake_get_current_user():
            return user

        app.dependency_overrides[get_current_user] = _fake_get_current_user

        with patch("main.resolve_org_for_user") as mock_resolve, patch(
            "main.list_aws_connections_for_org"
        ) as mock_list:
            mock_resolve.return_value = ("org-a", "OWNER")
            mock_list.return_value = []

            client = TestClient(app)
            resp = client.get("/api/aws/connections")
            assert resp.status_code == 200
            # Verify resolve_org_for_user was called (not client-provided org_id)
            mock_resolve.assert_called_once_with(user, None, permission="view_aws_connections")

        app.dependency_overrides.clear()

    def test_cross_tenant_access_prevented(self):
        """Verify a user from org A cannot access org B's resources."""
        from fastapi.testclient import TestClient
        from main import app, get_current_user
        from auth import AuthenticatedUser, AuthorizationError

        user = self._make_user()

        async def _fake_get_current_user():
            return user

        app.dependency_overrides[get_current_user] = _fake_get_current_user

        with patch("main.resolve_org_for_user") as mock_resolve:
            # Simulate user trying to access org B's resources
            mock_resolve.side_effect = AuthorizationError("Access denied")

            client = TestClient(app)
            resp = client.get(
                "/api/organizations/org-b/members",
                headers={"Authorization": "Bearer fake-token"},
            )
            assert resp.status_code == 403

        app.dependency_overrides.clear()

    def test_server_metrics_requires_jwt_auth(self):
        """Verify server metrics endpoint requires JWT auth."""
        from fastapi.testclient import TestClient
        from main import app, get_current_user, authorize_server
        from auth import AuthenticatedUser

        user = self._make_user()

        async def _fake_get_current_user():
            return user

        app.dependency_overrides[get_current_user] = _fake_get_current_user

        with patch("main.authorize_server") as mock_authorize:
            mock_authorize.return_value = {"id": "srv-1", "organization_id": "org-a"}

            client = TestClient(app)
            resp = client.get("/api/servers/srv-1/metrics")
            assert resp.status_code == 200
            mock_authorize.assert_called_once_with(user, "srv-1", permission="view_resources")

        app.dependency_overrides.clear()

    def test_no_client_provided_user_id_accepted(self):
        """Verify endpoints do not accept client-provided user_id query params."""
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        # The endpoint should NOT have user_id as a query parameter
        # This test verifies the endpoint signature doesn't accept it
        import inspect
        from main import server_metrics

        sig = inspect.signature(server_metrics)
        param_names = list(sig.parameters.keys())
        assert "user_id" not in param_names

    def test_no_client_provided_org_id_accepted(self):
        """Verify endpoints do not accept client-provided org_id query params."""
        import inspect
        from main import get_account_costs

        sig = inspect.signature(get_account_costs)
        param_names = list(sig.parameters.keys())
        assert "org_id" not in param_names
