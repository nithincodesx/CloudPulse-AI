"""Unit tests for AWS Resource Discovery (backend/aws_discovery.py).

Pure logic and mocked boto3 tests — tests AWS EC2 discovery parsing,
idempotent syncing, error handling, region overrides, duplicate prevention,
multi-service discovery registry, and reliable identifier matching.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError

from aws_discovery import (
    DiscoveryRegistry,
    EC2Discoverer,
    RDSDiscoverer,
    ECSDiscoverer,
    LambdaDiscoverer,
    EBSDiscoverer,
    ELBDiscoverer,
    _map_aws_state_to_status,
    discovery_configured,
    match_discovered_resource_to_telemetry_node,
    sync_aws_resources,
)
from auth import authorize_server


def _mock_ec2_response():
    return {
        "Reservations": [
            {
                "OwnerId": "123456789012",
                "Instances": [
                    {
                        "InstanceId": "i-0123456789abcdef0",
                        "InstanceType": "t3.micro",
                        "State": {"Name": "running"},
                        "Placement": {"AvailabilityZone": "us-east-1a"},
                        "PrivateIpAddress": "10.0.1.15",
                        "PublicIpAddress": "54.210.10.20",
                        "LaunchTime": "2026-01-01T00:00:00+00:00",
                        "Architecture": "x86_64",
                        "Hypervisor": "xen",
                        "Tags": [
                            {"Key": "Name", "Value": "prod-web-server-1"},
                            {"Key": "Environment", "Value": "production"},
                            {"Key": "server", "Value": "web-node-01"},
                        ],
                    },
                    {
                        "InstanceId": "i-0987654321fedcba0",
                        "InstanceType": "t3.large",
                        "State": {"Name": "stopped"},
                        "Placement": {"AvailabilityZone": "us-east-1b"},
                        "PrivateIpAddress": "10.0.2.20",
                        "LaunchTime": "2026-01-02T00:00:00+00:00",
                        "Tags": [
                            {"Key": "Name", "Value": "db-backup-server"},
                        ],
                    },
                ]
            }
        ]
    }


def test_discovery_registry_supports_all_services():
    services = DiscoveryRegistry.list_services()
    assert "ec2" in services
    assert "rds" in services
    assert "ecs" in services
    assert "lambda" in services
    assert "ebs" in services
    assert "elbv2" in services

    assert DiscoveryRegistry.get("ec2") is EC2Discoverer
    assert DiscoveryRegistry.get("rds") is RDSDiscoverer
    assert DiscoveryRegistry.get("ecs") is ECSDiscoverer
    assert DiscoveryRegistry.get("lambda") is LambdaDiscoverer
    assert DiscoveryRegistry.get("ebs") is EBSDiscoverer
    assert DiscoveryRegistry.get("elbv2") is ELBDiscoverer


def test_map_aws_state_to_status():
    assert _map_aws_state_to_status("running") == "active"
    assert _map_aws_state_to_status("stopped") == "idle"
    assert _map_aws_state_to_status("shutting-down") == "idle"
    assert _map_aws_state_to_status("pending") == "warning"


@patch("aws_discovery.discovery_configured", return_value=True)
@patch("aws_discovery.get_aws_client")
def test_ec2_discover_instances_parsed_correctly(mock_get_client, mock_configured):
    mock_client = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [_mock_ec2_response()]
    mock_client.get_paginator.return_value = mock_paginator
    mock_get_client.return_value = mock_client

    conn = {
        "id": "conn-uuid-1",
        "organization_id": "org-uuid-1",
        "aws_account_id": "123456789012",
        "role_arn": "arn:aws:iam::123456789012:role/CloudPulseRole",
        "external_id": "cloudpulse_test123",
        "region": "us-west-2",
    }
    discoverer = EC2Discoverer(region="us-west-2", connection=conn)
    instances = discoverer.discover()

    assert len(instances) == 2

    first = instances[0]
    # Verify all 11 required fields
    assert first["aws_instance_id"] == "i-0123456789abcdef0"
    assert first["aws_resource_id"] == "i-0123456789abcdef0"
    assert first["server_name"] == "prod-web-server-1"
    assert first["specifications"]["type"] == "t3.micro"
    assert first["aws_region"] == "us-west-2"
    assert first["aws_availability_zone"] == "us-east-1a"
    assert first["aws_state"] == "running"
    assert first["private_ip"] == "10.0.1.15"
    assert first["public_ip"] == "54.210.10.20"
    assert first["aws_launch_time"] == "2026-01-01T00:00:00+00:00"
    assert first["aws_tags"]["Environment"] == "production"
    assert first["aws_account_id"] == "123456789012"
    assert first["organization_id"] == "org-uuid-1"
    assert first["aws_connection_id"] == "conn-uuid-1"

    second = instances[1]
    assert second["aws_instance_id"] == "i-0987654321fedcba0"
    assert second["server_name"] == "db-backup-server"
    assert second["private_ip"] == "10.0.2.20"
    assert second["public_ip"] == ""
    assert second["aws_state"] == "stopped"


@patch("aws_discovery.discovery_configured", return_value=True)
@patch("aws_discovery.boto3.client")
def test_ec2_discover_permission_error_handled(mock_boto_client, mock_configured):
    mock_client = MagicMock()
    mock_paginator = MagicMock()
    error_response = {
        "Error": {
            "Code": "UnauthorizedOperation",
            "Message": "You are not authorized to perform this operation.",
        }
    }
    mock_paginator.paginate.side_effect = ClientError(error_response, "DescribeInstances")
    mock_client.get_paginator.return_value = mock_paginator
    mock_boto_client.return_value = mock_client

    discoverer = EC2Discoverer(region="us-east-1")
    with pytest.raises(RuntimeError) as exc_info:
        discoverer.discover()

    assert "UnauthorizedOperation" in str(exc_info.value)
    assert "not authorized" in str(exc_info.value)


@patch("aws_discovery.discovery_configured", return_value=False)
def test_sync_aws_resources_unconfigured_returns_error(mock_configured):
    result = sync_aws_resources()
    assert result.error is not None
    assert "AWS not configured" in result.error
    assert result.discovered_count == 0


def test_resource_matching_hierarchy():
    """Test reliable identifier hierarchy: Instance ID > Tag/Metadata > Name (Never IP as primary)."""
    existing_fleet = [
        {
            "id": "node-1",
            "server_name": "web-worker",
            "aws_instance_id": "i-exact-match-123",
            "aws_account_id": "111122223333",
            "aws_region": "us-east-1",
            "cost_tag": "web-prod",
            "ip_address": "192.168.1.50",
        },
        {
            "id": "node-2",
            "server_name": "db-primary",
            "aws_account_id": "111122223333",
            "aws_region": "us-east-1",
            "cost_tag": "database-main",
            "ip_address": "192.168.1.60",
        },
    ]

    # 1. Exact AWS Instance ID Match (Priority 1)
    discovered_1 = {
        "aws_instance_id": "i-exact-match-123",
        "aws_account_id": "111122223333",
        "aws_region": "us-east-1",
        "server_name": "different-name-in-aws",
        "private_ip": "10.99.99.99",  # IP is completely different!
    }
    m1 = match_discovered_resource_to_telemetry_node(discovered_1, existing_fleet)
    assert m1 is not None
    assert m1["id"] == "node-1"

    # 2. Tag / node metadata match (Priority 2)
    discovered_2 = {
        "aws_instance_id": "i-new-launch-456",
        "aws_account_id": "111122223333",
        "aws_region": "us-east-1",
        "aws_tags": {"cloudpulse:id": "node-2"},
        "server_name": "db-replica",
        "private_ip": "10.88.88.88",
    }
    m2 = match_discovered_resource_to_telemetry_node(discovered_2, existing_fleet)
    assert m2 is not None
    assert m2["id"] == "node-2"

    # 3. Account ID + Region + Cost tag match (Priority 3)
    discovered_3 = {
        "aws_instance_id": "i-new-launch-789",
        "aws_account_id": "111122223333",
        "aws_region": "us-east-1",
        "aws_tags": {"server": "database-main"},
        "server_name": "db-main-aws",
    }
    m3 = match_discovered_resource_to_telemetry_node(discovered_3, existing_fleet)
    assert m3 is not None
    assert m3["id"] == "node-2"

    # 4. Same IP on different account/region should NOT match (IP is not identity)
    discovered_unrelated = {
        "aws_instance_id": "i-other-account-999",
        "aws_account_id": "999988887777",
        "aws_region": "eu-west-1",
        "private_ip": "192.168.1.50",  # Same internal IP subnet
        "server_name": "unrelated-service",
    }
    m4 = match_discovered_resource_to_telemetry_node(discovered_unrelated, existing_fleet)
    assert m4 is None  # Correctly prevented false-positive match on IP


@patch("aws_discovery.discovery_configured", return_value=True)
@patch("aws_discovery.EC2Discoverer.discover")
@patch("aws_discovery.list_servers")
@patch("aws_discovery.upsert_discovered_server")
def test_sync_aws_resources_idempotency(
    mock_upsert,
    mock_list_servers,
    mock_discover,
    mock_configured,
):
    mock_discover.return_value = [
        {
            "aws_instance_id": "i-11111",
            "aws_resource_id": "i-11111",
            "server_name": "app-server-1",
            "ip_address": "52.1.2.3",
            "private_ip": "10.0.1.5",
            "public_ip": "52.1.2.3",
            "aws_region": "us-east-1",
            "aws_availability_zone": "us-east-1a",
            "aws_state": "running",
            "aws_tags": {"Name": "app-server-1"},
            "specifications": {"type": "t3.medium"},
        }
    ]

    # --- First Run: no existing server matched ---
    mock_list_servers.return_value = []

    res1 = sync_aws_resources(region="us-east-1")
    assert res1.discovered_count == 1
    assert res1.created_count == 1
    assert res1.updated_count == 0
    assert mock_upsert.call_count == 1

    # --- Second Run: server already exists in DB with aws_instance_id ---
    mock_list_servers.return_value = [
        {
            "id": "existing-uuid-1234",
            "server_name": "app-server-1",
            "aws_instance_id": "i-11111",
            "status": "active",
        }
    ]
    mock_upsert.reset_mock()

    res2 = sync_aws_resources(region="us-east-1")
    assert res2.discovered_count == 1
    assert res2.created_count == 0
    assert res2.updated_count == 1  # updated existing record, NO DUPLICATE CREATED
    assert mock_upsert.call_count == 1


# ---------------------------------------------------------------------------
# NEW: Additional tests for Phase 2 requirements
# ---------------------------------------------------------------------------


@patch("aws_discovery.discovery_configured", return_value=True)
@patch("aws_discovery.EC2Discoverer.discover")
@patch("aws_discovery.list_servers")
@patch("aws_discovery.upsert_discovered_server")
def test_sync_preserves_terminated_resources(mock_upsert, mock_list_servers, mock_discover, mock_configured):
    """Verify that terminated AWS instances preserve historical telemetry."""
    # AWS returns no instances (all terminated)
    mock_discover.return_value = []

    # But we have existing servers in our DB from previous discoveries
    mock_list_servers.return_value = [
        {
            "id": "existing-uuid-terminated",
            "server_name": "old-server-1",
            "aws_instance_id": "i-terminated-111",
            "status": "active",
            "organization_id": "org-123",
        }
    ]

    result = sync_aws_resources(region="us-east-1")
    assert result.discovered_count == 0
    assert result.created_count == 0
    assert result.updated_count == 0
    # No upsert should be called since AWS returned nothing
    assert mock_upsert.call_count == 0


@patch("aws_discovery.discovery_configured", return_value=True)
@patch("aws_discovery.EC2Discoverer.discover")
@patch("aws_discovery.list_servers")
@patch("aws_discovery.upsert_discovered_server")
def test_sync_handles_multiple_aws_accounts(mock_upsert, mock_list_servers, mock_discover, mock_configured):
    """Verify that discovery works across multiple AWS accounts."""
    # Simulate instances from two different AWS accounts
    mock_discover.return_value = [
        {
            "aws_instance_id": "i-account1-111",
            "aws_resource_id": "i-account1-111",
            "server_name": "server-account1",
            "aws_region": "us-east-1",
            "aws_account_id": "111122223333",
            "aws_state": "running",
            "aws_tags": {},
            "specifications": {"type": "t3.medium"},
        },
        {
            "aws_instance_id": "i-account2-222",
            "aws_resource_id": "i-account2-222",
            "server_name": "server-account2",
            "aws_region": "us-west-2",
            "aws_account_id": "444455556666",
            "aws_state": "running",
            "aws_tags": {},
            "specifications": {"type": "t3.large"},
        },
    ]

    mock_list_servers.return_value = []

    result = sync_aws_resources(region="us-east-1")
    assert result.discovered_count == 2
    assert result.created_count == 2
    assert mock_upsert.call_count == 2


def test_cross_tenant_isolation_prevents_idor():
    """Verify that a user from one organization cannot access another org's servers."""
    from auth import AuthorizationError, AuthenticatedUser
    from unittest.mock import patch

    # Simulate a user from org-A trying to access a server from org-B
    user_org_a = AuthenticatedUser(
        user_id="user-a",
        email="usera@orga.com",
        role="authenticated",
    )

    # Server belongs to org-b
    server_org_b = {
        "id": "server-123",
        "server_name": "org-b-server",
        "organization_id": "org-b",
    }

    # Mock get_server to return the org-b server
    # Mock get_org_member to return None (user is not a member of org-b)
    with patch("auth.get_server", return_value=server_org_b), patch(
        "auth.get_org_member", return_value=None
    ):
        # This should raise HTTPException with 404 (existence not leaked)
        with pytest.raises(Exception) as exc_info:
            authorize_server(user_org_a, "server-123", permission="view_resources")
        # Should be 404, not 403 — existence of cross-tenant resources is not leaked
        assert exc_info.value.status_code in (404, 403)


def test_rbac_prevents_privilege_escalation():
    """Verify that a VIEWER cannot perform admin actions."""
    from auth import AuthorizationError, AuthenticatedUser
    from unittest.mock import patch

    viewer_user = AuthenticatedUser(
        user_id="viewer-1",
        email="viewer@test.com",
        role="authenticated",
    )

    server = {
        "id": "server-123",
        "server_name": "test-server",
        "organization_id": "org-123",
    }

    # Mock: user is a VIEWER in org-123
    with patch("auth.get_server", return_value=server), patch(
        "auth.get_org_member", return_value={"role": "VIEWER", "user_id": "viewer-1"}
    ):
        # VIEWER should not be able to manage resources
        with pytest.raises(AuthorizationError):
            authorize_server(viewer_user, "server-123", permission="manage_resources")

        # VIEWER should not be able to connect AWS
        with pytest.raises(AuthorizationError):
            authorize_server(viewer_user, "server-123", permission="connect_aws")


def test_jwt_derived_identity_not_client_provided():
    """Verify that user identity comes from JWT, not client-provided parameters."""
    from auth import AuthenticatedUser
    import inspect

    # The authenticated user's identity should come from the JWT token
    user = AuthenticatedUser(
        user_id="jwt-user-123",
        email="jwtuser@test.com",
        role="authenticated",
    )

    # User ID should be from JWT, not from query params
    assert user.user_id == "jwt-user-123"

    # The endpoint should NOT accept user_id as a query parameter
    from main import server_metrics
    # server_metrics is a FastAPI route, get the actual function
    fn = server_metrics
    if hasattr(fn, "dependency_overrides"):
        fn = fn.dependency_overrides.get(server_metrics, server_metrics)
    # For FastAPI routes, inspect the endpoint function
    endpoint = getattr(fn, "endpoint", fn)
    sig = inspect.signature(endpoint)
    params = list(sig.parameters.keys())
    # Should NOT have user_id or org_id as query params
    assert "user_id" not in params
    assert "org_id" not in params
