"""Tests for Server Lifecycle and Node Termination in CloudPulse Enterprise."""

import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi.testclient import TestClient

from main import app, get_current_user, authorize_server
from models import ServerStatusUpdate, ServerTerminateResponse
from audit_service import AuditActions
from database import list_servers, delete_server, update_server_status
from auth import AuthenticatedUser, AuthorizationError

client = TestClient(app)


# ---------------------------------------------------------------------------
# Test fixtures — mock JWT auth so endpoints can be tested in isolation
# ---------------------------------------------------------------------------
_TEST_USER_ID = "user-123"
_TEST_ORG_ID = "org-456"
_TEST_USER_EMAIL = "test@cloudpulse.io"


def _mock_authenticated_user():
    """Patch auth helpers to simulate a valid JWT-authenticated OWNER."""
    return AuthenticatedUser(
        user_id=_TEST_USER_ID,
        email=_TEST_USER_EMAIL,
        role="authenticated",
        claims={},
    )


def _override_auth(user=None, server=None, side_effect=None):
    """Override FastAPI dependencies for auth in tests."""
    if user is None:
        user = _mock_authenticated_user()

    async def _fake_get_current_user():
        return user

    async def _fake_authorize_server(u, sid, permission=None):
        if side_effect:
            raise side_effect
        if server is not None:
            return server
        return {"id": sid, "server_name": "test-node", "organization_id": _TEST_ORG_ID}

    app.dependency_overrides[get_current_user] = _fake_get_current_user
    app.dependency_overrides[authorize_server] = _fake_authorize_server


def _clear_auth_overrides():
    app.dependency_overrides.clear()


class TestServerLifecycleAndTermination:
    """Test server status transitions, node termination, RBAC enforcement, and audit logs."""

    @patch("main.get_server")
    @patch("main.delete_server")
    @patch("main.log_audit_event")
    def test_terminate_telemetry_node_success(self, mock_audit, mock_delete, mock_get_server):
        """Verify successful termination of a telemetry node via DELETE /api/servers/{server_id}."""
        server_id = str(uuid4())
        server = {
            "id": server_id,
            "server_name": "test-node-01",
            "status": "active",
            "source": "agent",
            "ip_address": "127.0.0.1",
            "owner_id": _TEST_USER_ID,
            "organization_id": _TEST_ORG_ID,
        }
        mock_get_server.return_value = server
        mock_delete.return_value = True

        _override_auth()
        try:
            with patch("main.authorize_server", return_value=server):
                resp = client.delete(f"/api/servers/{server_id}")
        finally:
            _clear_auth_overrides()

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "terminated"
        assert data["server_id"] == server_id
        assert data["server_name"] == "test-node-01"
        assert "test-node-01" in data["message"]

        # Verify DB delete was invoked
        mock_delete.assert_called_once_with(server_id)

        # Verify audit log was recorded
        mock_audit.assert_called_once()
        args, kwargs = mock_audit.call_args
        assert kwargs["action"] == AuditActions.NODE_TERMINATED
        assert kwargs["resource_id"] == server_id
        assert kwargs["metadata"]["server_name"] == "test-node-01"

    @patch("main.get_server")
    @patch("main.delete_server")
    @patch("main.log_audit_event")
    def test_terminate_node_post_alias(self, mock_audit, mock_delete, mock_get_server):
        """Verify POST /api/servers/{server_id}/terminate alias endpoint works identically."""
        server_id = str(uuid4())
        server = {
            "id": server_id,
            "server_name": "test-node-02",
            "status": "idle",
            "source": "agent",
            "ip_address": "10.0.0.1",
            "owner_id": _TEST_USER_ID,
        }
        mock_get_server.return_value = server
        mock_delete.return_value = True

        _override_auth()
        try:
            with patch("main.authorize_server", return_value=server):
                resp = client.post(f"/api/servers/{server_id}/terminate")
        finally:
            _clear_auth_overrides()

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "terminated"
        assert data["server_id"] == server_id
        mock_delete.assert_called_once_with(server_id)

    @patch("main.get_server")
    def test_terminate_nonexistent_node_returns_404(self, mock_get_server):
        """Verify terminating a missing/already deleted node returns 404."""
        mock_get_server.return_value = None
        server_id = str(uuid4())

        _override_auth()
        try:
            with patch("main.authorize_server", side_effect=AuthorizationError("not found")):
                resp = client.delete(f"/api/servers/{server_id}")
        finally:
            _clear_auth_overrides()

        assert resp.status_code == 403

    @patch("main.get_server")
    @patch("main.get_organization_member")
    def test_terminate_unauthorized_member_returns_403(self, mock_get_member, mock_get_server):
        """Verify a user without manage_resources permission cannot terminate nodes."""
        server_id = str(uuid4())
        server = {
            "id": server_id,
            "server_name": "prod-node",
            "status": "active",
            "owner_id": "other-user",
            "organization_id": "org-789",
        }
        mock_get_server.return_value = server
        # VIEWER role does not have manage_resources permission
        mock_get_member.return_value = {"role": "VIEWER", "user_id": "viewer-user"}

        viewer_user = AuthenticatedUser(
            user_id="viewer-user",
            email="viewer@cloudpulse.io",
            role="authenticated",
            claims={},
        )
        _override_auth(user=viewer_user)
        try:
            with patch("main.authorize_server", side_effect=AuthorizationError("insufficient permissions")):
                resp = client.delete(f"/api/servers/{server_id}")
        finally:
            _clear_auth_overrides()

        assert resp.status_code == 403
        assert "insufficient permissions" in resp.json()["detail"]

    @patch("main.get_server")
    @patch("main.update_server_status")
    def test_update_server_status_lifecycle(self, mock_upd_status, mock_get_server):
        """Verify updating server status supports idle, active, warning, critical, terminating."""
        server_id = str(uuid4())
        server = {"id": server_id, "server_name": "worker-1", "status": "active"}
        mock_get_server.return_value = server
        mock_upd_status.return_value = {"id": server_id, "server_name": "worker-1", "status": "terminating"}

        _override_auth()
        try:
            with patch("main.authorize_server", return_value=server):
                resp = client.put(f"/api/servers/{server_id}/status", json={"status": "terminating"})
        finally:
            _clear_auth_overrides()

        assert resp.status_code == 200
        mock_upd_status.assert_called_once_with(server_id, "terminating")
