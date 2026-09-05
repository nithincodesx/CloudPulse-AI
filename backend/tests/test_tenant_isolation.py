"""Unit tests for Tenant Isolation, Organizations, and Role-Based Access Control (RBAC)."""

import pytest
from unittest.mock import patch, MagicMock
from tenant_service import (
    ROLE_HIERARCHY,
    verify_permission,
    provision_organization,
    invite_member_to_org,
    change_member_role,
    remove_member_from_org,
    slugify,
)
from billing_service import calculate_organization_usage
from audit_service import log_audit_event, AuditActions, sanitize_metadata


class TestTenantIsolationAndRBAC:
    """Test multi-tenant workspaces and RBAC rule enforcement."""

    def test_role_hierarchy_and_permissions(self):
        """Verify OWNER, ADMIN, MEMBER, VIEWER permission matrix."""
        # OWNER can do everything
        assert verify_permission("OWNER", "manage_org_settings") is True
        assert verify_permission("OWNER", "connect_aws") is True
        assert verify_permission("OWNER", "manage_members") is True
        assert verify_permission("OWNER", "view_costs") is True

        # ADMIN can manage AWS and resources, but not org deletion/billing
        assert verify_permission("ADMIN", "connect_aws") is True
        assert verify_permission("ADMIN", "manage_resources") is True
        assert verify_permission("ADMIN", "manage_org_settings") is False
        assert verify_permission("ADMIN", "delete_org") is False

        # MEMBER can view, investigate incidents, but not connect AWS or manage members
        assert verify_permission("MEMBER", "view_resources") is True
        assert verify_permission("MEMBER", "investigate_incidents") is True
        assert verify_permission("MEMBER", "connect_aws") is False
        assert verify_permission("MEMBER", "manage_members") is False

        # VIEWER is read-only
        assert verify_permission("VIEWER", "view_resources") is True
        assert verify_permission("VIEWER", "view_costs") is True
        assert verify_permission("VIEWER", "investigate_incidents") is False
        assert verify_permission("VIEWER", "connect_aws") is False

    def test_slugify_uniqueness(self):
        """Verify slug generation creates URL-safe slugs with random entropy."""
        slug1 = slugify("Acme Cloud Corp")
        slug2 = slugify("Acme Cloud Corp")
        assert slug1.startswith("acme-cloud-corp-")
        assert slug2.startswith("acme-cloud-corp-")
        assert slug1 != slug2

    @patch("tenant_service.create_organization")
    @patch("tenant_service.create_organization_member")
    @patch("tenant_service.log_audit_event")
    def test_provision_organization_sets_owner(self, mock_audit, mock_member, mock_create):
        """Test workspace creation sets creator as OWNER and logs audit event."""
        mock_create.return_value = {
            "id": "org-123",
            "name": "Stark Industries",
            "slug": "stark-industries-abc",
            "plan_tier": "pro",
        }
        org = provision_organization(
            name="Stark Industries",
            user_id="user-999",
            user_email="tony@stark.com",
            plan_tier="pro",
        )

        assert org["id"] == "org-123"
        assert org["user_role"] == "OWNER"
        mock_member.assert_called_once()
        member_args = mock_member.call_args[0][0]
        assert member_args["organization_id"] == "org-123"
        assert member_args["user_id"] == "user-999"
        assert member_args["role"] == "OWNER"
        mock_audit.assert_called_once()

    @patch("tenant_service.create_organization_member")
    @patch("tenant_service.log_audit_event")
    def test_invite_member(self, mock_audit, mock_member):
        """Test member invitation with valid roles."""
        mock_member.return_value = {"id": "mem-1", "role": "MEMBER"}
        res = invite_member_to_org("org-123", "pepper@stark.com", "ADMIN", "user-999")
        assert res["id"] == "mem-1"
        mock_audit.assert_called_once()

        # Cannot invite another OWNER
        with pytest.raises(ValueError):
            invite_member_to_org("org-123", "rhodey@stark.com", "OWNER", "user-999")

    @patch("tenant_service.update_organization_member_role")
    @patch("tenant_service.log_audit_event")
    def test_change_member_role(self, mock_audit, mock_update):
        """Test member role update."""
        mock_update.return_value = {"id": "mem-1", "role": "ADMIN"}
        res = change_member_role("org-123", "mem-1", "ADMIN", "user-999")
        assert res["role"] == "ADMIN"
        mock_audit.assert_called_once()


class TestAuditLogSecurity:
    """Test audit log sanitization and tamper-evidence."""

    def test_sanitize_metadata_removes_secrets(self):
        """Ensure no tokens, secret keys, or passwords are saved into audit metadata."""
        dirty_meta = {
            "aws_account_id": "123456789012",
            "region": "us-east-1",
            "secret_access_key": "SUPER_SECRET_KEY_DO_NOT_LEAK",
            "session_token": "sts_token_12345",
            "nested": {
                "password": "my_password",
                "safe_value": "hello",
            },
        }
        clean = sanitize_metadata(dirty_meta)
        assert clean["aws_account_id"] == "123456789012"
        assert clean["region"] == "us-east-1"
        assert clean["secret_access_key"] == "[REDACTED]"
        assert clean["session_token"] == "[REDACTED]"
        assert clean["nested"]["password"] == "[REDACTED]"
        assert clean["nested"]["safe_value"] == "hello"


class TestBillingUsage:
    """Test SaaS billing usage metrics aggregation."""

    @patch("billing_service.get_organization_by_id")
    @patch("billing_service.list_aws_connections_for_org")
    @patch("billing_service.list_servers_for_org")
    @patch("billing_service.list_alerts")
    @patch("billing_service.get_telemetry_metrics_count")
    def test_calculate_organization_usage(
        self, mock_telemetry, mock_alerts, mock_servers, mock_connections, mock_org
    ):
        mock_org.return_value = {
            "id": "org-123",
            "plan_tier": "starter",
            "max_aws_connections": 10,
            "retention_days": 60,
        }
        mock_connections.return_value = [{"id": "c1"}, {"id": "c2"}]
        mock_servers.return_value = [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]
        mock_alerts.return_value = [{"id": "a1", "organization_id": "org-123"}]
        mock_telemetry.side_effect = [1500, 45000]

        usage = calculate_organization_usage("org-123")
        assert usage["organization_id"] == "org-123"
        assert usage["plan_tier"] == "starter"
        assert usage["connected_aws_accounts"] == 2
        assert usage["max_aws_connections"] == 10
        assert usage["monitored_nodes"] == 3
        assert usage["active_alerts"] == 1
        assert usage["telemetry_metrics_24h"] == 1500
        assert usage["telemetry_metrics_30d"] == 45000
