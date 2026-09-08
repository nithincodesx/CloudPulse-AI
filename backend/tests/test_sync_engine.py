"""Unit tests for Centralized AWS Sync Engine and Health Diagnostics."""

import pytest
from unittest.mock import patch, MagicMock
from sync_engine import run_centralized_sync
from aws_credentials import diagnose_connection_health


class TestSyncEngineAndHealth:
    """Test idempotent synchronization and granular health evaluation."""

    @patch("aws_credentials._SESSION_CACHE.get_session")
    def test_diagnose_connection_health_success(self, mock_get_session):
        """Test healthy AWS connection returns PASS on all 4 checks."""
        mock_session = MagicMock()
        mock_ec2 = MagicMock()
        mock_ce = MagicMock()
        mock_session.client.side_effect = lambda s, **kw: mock_ec2 if s == "ec2" else mock_ce
        mock_get_session.return_value = mock_session

        conn = {
            "id": "conn-123",
            "role_arn": "arn:aws:iam::123456789012:role/CloudPulseRole",
            "external_id": "cloudpulse_abc123",
            "aws_account_id": "123456789012",
            "region": "us-east-1",
        }

        diag = diagnose_connection_health(conn)
        assert diag["health_status"] == "HEALTHY"
        assert diag["checks"]["assume_role"]["status"] == "PASS"
        assert diag["checks"]["account_id"]["status"] == "PASS"
        assert diag["checks"]["ec2_permissions"]["status"] == "PASS"
        assert diag["checks"]["cost_explorer_permissions"]["status"] == "PASS"

    @patch("aws_credentials._SESSION_CACHE.get_session")
    def test_diagnose_connection_health_missing_cost_explorer(self, mock_get_session):
        """Test DEGRADED status when Cost Explorer permissions are missing."""
        mock_session = MagicMock()
        mock_ec2 = MagicMock()
        mock_ce = MagicMock()
        mock_ce.get_dimension_values.side_effect = Exception("AccessDenied: User is not authorized to perform ce:GetDimensionValues")
        mock_session.client.side_effect = lambda s, **kw: mock_ec2 if s == "ec2" else mock_ce
        mock_get_session.return_value = mock_session

        conn = {
            "id": "conn-123",
            "role_arn": "arn:aws:iam::123456789012:role/CloudPulseRole",
            "external_id": "cloudpulse_abc123",
            "aws_account_id": "123456789012",
            "region": "us-east-1",
        }

        diag = diagnose_connection_health(conn)
        assert diag["health_status"] == "DEGRADED"
        assert diag["checks"]["cost_explorer_permissions"]["status"] == "FAIL"
        assert "Cost Explorer permission" in diag["checks"]["cost_explorer_permissions"]["message"]

    @patch("sync_engine.get_aws_connection")
    @patch("sync_engine.update_aws_connection")
    @patch("sync_engine.diagnose_connection_health")
    @patch("sync_engine.sync_aws_resources")
    @patch("sync_engine.sync_daily_costs")
    @patch("sync_engine.list_servers_for_connection")
    @patch("sync_engine.run_fleet_optimization_analysis")
    @patch("sync_engine.log_audit_event")
    def test_run_centralized_sync_success(
        self,
        mock_audit,
        mock_opt,
        mock_servers,
        mock_cost_sync,
        mock_discovery,
        mock_diag,
        mock_update_conn,
        mock_get_conn,
    ):
        """Test full centralized idempotent sync pipeline execution."""
        mock_get_conn.return_value = {
            "id": "conn-123",
            "organization_id": "org-456",
            "role_arn": "arn:aws:iam::123456789012:role/Role",
            "external_id": "cloudpulse_xyz",
            "region": "us-east-1",
        }
        mock_diag.return_value = {
            "health_status": "HEALTHY",
            "checks": {"assume_role": {"status": "PASS"}},
            "summary": "OK",
        }
        mock_discovery.return_value = {
            "discovered_count": 5,
            "created_count": 2,
            "updated_count": 3,
            "matched_count": 5,
            "instances": [],
            "region": "us-east-1",
            "error": None,
        }
        mock_cost_sync.return_value = {
            "days_synced": 30,
            "matched": 5,
            "unmatched": [],
            "total_amount": 1250.0,
            "error": None,
        }
        mock_servers.return_value = []
        mock_opt.return_value = {"total_opportunities_count": 3}

        result = run_centralized_sync("conn-123", organization_id="org-456", actor_id="user-1")

        assert result["status"] == "SUCCESS"
        assert result["ec2_discovery"]["discovered_count"] == 5
        assert result["cost_sync"]["days_synced"] == 30
        assert result["recommendations_generated"] == 3
        mock_audit.assert_called_once()
