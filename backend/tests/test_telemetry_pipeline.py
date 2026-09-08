"""Tests for the complete Telemetry Pipeline in CloudPulse Enterprise."""

import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from fastapi.testclient import TestClient

from main import app, get_current_user, authorize_server
from database import sync_known_server, insert_metric, latest_metrics, get_server_by_token, delete_server
from telemetry_agent import collect_metrics
from auth import AuthenticatedUser

client = TestClient(app)

# Test auth fixtures
_TEST_USER = AuthenticatedUser(
    user_id="test-user",
    email="test@cloudpulse.io",
    role="authenticated",
    claims={},
)


def _override_auth_for_tests():
    """Override JWT auth dependencies so pipeline tests can run without real JWTs."""
    async def _fake_get_current_user():
        return _TEST_USER

    async def _fake_authorize_server(user, server_id, permission=None):
        return {"id": server_id, "server_name": "test-node", "organization_id": "test-org"}

    app.dependency_overrides[get_current_user] = _fake_get_current_user
    app.dependency_overrides[authorize_server] = _fake_authorize_server


class TestTelemetryPipeline:
    """Test telemetry collection, token authentication, validation, and storage."""

    def test_collect_metrics_windows_safe(self):
        """Verify collect_metrics captures valid system stats without platform errors."""
        metrics = collect_metrics()
        assert "cpu_usage" in metrics
        assert isinstance(metrics["cpu_usage"], (int, float))
        assert 0.0 <= metrics["cpu_usage"] <= 100.0

        assert "ram_usage" in metrics
        assert isinstance(metrics["ram_usage"], (int, float))
        assert 0.0 <= metrics["ram_usage"] <= 100.0

        assert "network_traffic" in metrics
        assert isinstance(metrics["network_traffic"], (int, float))
        assert metrics["network_traffic"] >= 0.0

        assert "disk_usage" in metrics
        assert isinstance(metrics["disk_usage"], (int, float))
        assert 0.0 <= metrics["disk_usage"] <= 100.0

    def test_sync_node_and_ingest_telemetry_success(self):
        """Verify syncing a node and successfully ingesting real telemetry.

        Runs against the real Supabase now that the service-role key is
        configured, so the created node — and its metric rows via ON DELETE
        CASCADE — is removed again in the finally block to keep the live
        database clean between test runs.
        """
        _override_auth_for_tests()
        server_id = str(uuid4())
        token = "test_ingestion_token_" + str(uuid4())[:8]
        try:
            with patch("main.authorize_server", return_value={"id": server_id, "server_name": "test-node", "organization_id": "test-org"}):
                self._sync_node_and_ingest(server_id, token)
        finally:
            delete_server(server_id)
            app.dependency_overrides.clear()

    def _sync_node_and_ingest(self, server_id: str, token: str) -> None:
        # 1. Sync node into backend registry
        sync_resp = client.post(
            "/api/servers/sync-node",
            json={
                "id": server_id,
                "server_name": "telemetry-test-node",
                "ingestion_token": token,
                "ip_address": "127.0.0.1",
                "status": "active",
            },
        )
        assert sync_resp.status_code == 200
        assert sync_resp.json()["status"] == "synced"

        # 2. Post telemetry with valid bearer token
        metric_payload = {
            "cpu_usage": 24.5,
            "ram_usage": 61.2,
            "network_traffic": 14.8,
            "disk_usage": 45.0,
            "system_uptime": 12345.6,
            "process_count": 180,
        }
        headers = {"Authorization": f"Bearer {token}"}
        ingest_resp = client.post("/api/metrics", json=metric_payload, headers=headers)
        assert ingest_resp.status_code == 200
        data = ingest_resp.json()
        assert data["server_id"] == server_id
        assert data["cpu_usage"] == 24.5
        assert data["ram_usage"] == 61.2
        assert data["disk_usage"] == 45.0

        # 3. Retrieve historical metrics
        hist_resp = client.get(f"/api/servers/{server_id}/metrics")
        assert hist_resp.status_code == 200
        hist_data = hist_resp.json()
        assert len(hist_data) >= 1
        assert hist_data[-1]["cpu_usage"] == 24.5

    def test_ingest_missing_token_returns_401(self):
        """Verify request without Authorization header returns 401."""
        payload = {"cpu_usage": 10.0, "ram_usage": 20.0, "network_traffic": 5.0}
        resp = client.post("/api/metrics", json=payload)
        assert resp.status_code == 401
        assert "Invalid or missing" in resp.json()["detail"]

    def test_ingest_invalid_token_returns_401(self):
        """Verify request with unknown token returns 401."""
        payload = {"cpu_usage": 10.0, "ram_usage": 20.0, "network_traffic": 5.0}
        headers = {"Authorization": "Bearer non_existent_token_xyz"}
        resp = client.post("/api/metrics", json=payload, headers=headers)
        assert resp.status_code == 401
        assert "Invalid or missing" in resp.json()["detail"]

    def test_ingest_invalid_payload_validation(self):
        """Verify payload with out-of-bounds CPU percent is rejected with 422."""
        server_id = str(uuid4())
        token = "test_val_token_" + str(uuid4())[:8]
        sync_known_server({"id": server_id, "server_name": "val-node", "ingestion_token": token})

        headers = {"Authorization": f"Bearer {token}"}
        # CPU > 100 is invalid
        bad_payload = {"cpu_usage": 150.0, "ram_usage": 50.0, "network_traffic": 10.0}
        resp = client.post("/api/metrics", json=bad_payload, headers=headers)
        assert resp.status_code == 422
