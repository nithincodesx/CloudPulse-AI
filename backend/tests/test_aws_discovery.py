"""Unit tests for AWS Resource Discovery (backend/aws_discovery.py).

Pure logic and mocked boto3 tests — tests AWS EC2 discovery parsing,
idempotent syncing, error handling, region overrides, and duplicate prevention.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError

from aws_discovery import (
    EC2Discoverer,
    _map_aws_state_to_status,
    discovery_configured,
    sync_aws_resources,
)


def _mock_ec2_response():
    return {
        "Reservations": [
            {
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


def test_map_aws_state_to_status():
    assert _map_aws_state_to_status("running") == "active"
    assert _map_aws_state_to_status("stopped") == "idle"
    assert _map_aws_state_to_status("shutting-down") == "idle"
    assert _map_aws_state_to_status("pending") == "warning"


@patch("aws_discovery.discovery_configured", return_value=True)
@patch("aws_discovery.boto3.client")
def test_ec2_discover_instances_parsed_correctly(mock_boto_client, mock_configured):
    mock_client = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [_mock_ec2_response()]
    mock_client.get_paginator.return_value = mock_paginator
    mock_boto_client.return_value = mock_client

    discoverer = EC2Discoverer(region="us-west-2")
    instances = discoverer.discover()

    assert len(instances) == 2

    first = instances[0]
    assert first["aws_instance_id"] == "i-0123456789abcdef0"
    assert first["server_name"] == "prod-web-server-1"
    assert first["ip_address"] == "54.210.10.20"
    assert first["aws_region"] == "us-west-2"
    assert first["aws_availability_zone"] == "us-east-1a"
    assert first["aws_state"] == "running"
    assert first["specifications"]["type"] == "t3.micro"
    assert first["aws_tags"]["Environment"] == "production"

    second = instances[1]
    assert second["aws_instance_id"] == "i-0987654321fedcba0"
    assert second["server_name"] == "db-backup-server"
    assert second["ip_address"] == "10.0.2.20"  # fallback to private IP when public is absent
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


@patch("aws_discovery.discovery_configured", return_value=True)
@patch("aws_discovery.EC2Discoverer.discover")
@patch("aws_discovery.list_servers")
@patch("aws_discovery.get_server_by_aws_instance_id")
@patch("aws_discovery.upsert_discovered_server")
def test_sync_aws_resources_idempotency(
    mock_upsert,
    mock_get_by_aws_id,
    mock_list_servers,
    mock_discover,
    mock_configured,
):
    mock_discover.return_value = [
        {
            "aws_instance_id": "i-11111",
            "server_name": "app-server-1",
            "ip_address": "52.1.2.3",
            "aws_region": "us-east-1",
            "aws_availability_zone": "us-east-1a",
            "aws_state": "running",
            "aws_tags": {"Name": "app-server-1"},
            "specifications": {"type": "t3.medium"},
        }
    ]

    # --- First Run: no existing server matched by aws_instance_id or tag ---
    mock_get_by_aws_id.return_value = None
    mock_list_servers.return_value = []

    res1 = sync_aws_resources(region="us-east-1")
    assert res1.discovered_count == 1
    assert res1.created_count == 1
    assert res1.updated_count == 0
    assert mock_upsert.call_count == 1

    # --- Second Run: server already exists in DB with aws_instance_id ---
    mock_get_by_aws_id.return_value = {
        "id": "existing-uuid-1234",
        "server_name": "app-server-1",
        "aws_instance_id": "i-11111",
        "status": "active",
    }
    mock_list_servers.return_value = [mock_get_by_aws_id.return_value]
    mock_upsert.reset_mock()

    res2 = sync_aws_resources(region="us-east-1")
    assert res2.discovered_count == 1
    assert res2.created_count == 0
    assert res2.updated_count == 1  # updated existing record, NO DUPLICATE CREATED
    assert mock_upsert.call_count == 1
