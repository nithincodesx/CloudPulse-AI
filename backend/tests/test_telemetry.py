"""Unit tests for Expanded Server Telemetry (backend/telemetry_agent.py, models.py, main.py).

Tests metric collection, Pydantic schema validation, backward compatibility,
and the FastAPI /api/metrics ingestion endpoint.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from pydantic import ValidationError

from models import MetricPayload, MetricResponse
from telemetry_agent import collect_metrics


def test_collect_metrics_structure():
    """Verify collect_metrics returns standard and extended psutil host metrics."""
    metrics = collect_metrics()
    assert "cpu_usage" in metrics
    assert "ram_usage" in metrics
    assert "network_traffic" in metrics
    assert isinstance(metrics["cpu_usage"], float)
    assert isinstance(metrics["ram_usage"], float)
    assert isinstance(metrics["network_traffic"], float)

    # Extended metrics (present on supported systems)
    if "disk_usage" in metrics:
        assert 0.0 <= metrics["disk_usage"] <= 100.0
    if "process_count" in metrics:
        assert isinstance(metrics["process_count"], int)
        assert metrics["process_count"] > 0
    if "system_uptime" in metrics:
        assert isinstance(metrics["system_uptime"], float)
        assert metrics["system_uptime"] > 0.0


def test_metric_payload_validation_full():
    """Verify MetricPayload accepts full expanded telemetry payloads."""
    data = {
        "cpu_usage": 45.5,
        "ram_usage": 62.0,
        "network_traffic": 15.8,
        "disk_usage": 78.4,
        "disk_io": {"read_mb": 120.5, "write_mb": 45.2},
        "system_uptime": 86400.0,
        "load_average": [0.5, 0.4, 0.3],
        "process_count": 142,
        "network_stats": {"packets_sent": 1000, "packets_recv": 2000},
    }
    payload = MetricPayload(**data)
    assert payload.cpu_usage == 45.5
    assert payload.disk_usage == 78.4
    assert payload.process_count == 142
    assert payload.load_average == [0.5, 0.4, 0.3]


def test_metric_payload_validation_backward_compatibility():
    """Verify MetricPayload accepts legacy 3-field payloads without error."""
    legacy_data = {
        "cpu_usage": 32.1,
        "ram_usage": 50.0,
        "network_traffic": 4.5,
    }
    payload = MetricPayload(**legacy_data)
    assert payload.cpu_usage == 32.1
    assert payload.ram_usage == 50.0
    assert payload.network_traffic == 4.5
    assert payload.disk_usage is None
    assert payload.process_count is None
    assert payload.system_uptime is None


def test_metric_payload_out_of_bounds_raises():
    """Verify bounds checking on cpu_usage and ram_usage."""
    with pytest.raises(ValidationError):
        MetricPayload(cpu_usage=150.0, ram_usage=50.0, network_traffic=1.0)

    with pytest.raises(ValidationError):
        MetricPayload(cpu_usage=50.0, ram_usage=-5.0, network_traffic=1.0)


@patch("main.get_server_by_token")
@patch("main.insert_metric")
@patch("main.rpc_baseline", return_value=None)
def test_ingest_metrics_endpoint_full_payload(mock_baseline, mock_insert, mock_get_server):
    from main import app
    from fastapi.testclient import TestClient

    mock_get_server.return_value = {"id": "99999999-9999-9999-9999-999999999999"}
    mock_insert.return_value = {
        "id": "11111111-1111-1111-1111-111111111111",
        "server_id": "99999999-9999-9999-9999-999999999999",
        "cpu_usage": 42.0,
        "ram_usage": 55.0,
        "network_traffic": 10.0,
        "disk_usage": 35.0,
        "process_count": 120,
        "recorded_at": "2026-01-01T00:00:00+00:00",
    }

    client = TestClient(app)
    response = client.post(
        "/api/metrics",
        headers={"Authorization": "Bearer test-valid-token"},
        json={
            "cpu_usage": 42.0,
            "ram_usage": 55.0,
            "network_traffic": 10.0,
            "disk_usage": 35.0,
            "process_count": 120,
        },
    )

    if response.status_code != 200:
        print("TEST ERROR BODY:", response.json())

    assert response.status_code == 200
    res_data = response.json()
    assert res_data["cpu_usage"] == 42.0
    assert res_data["disk_usage"] == 35.0
    assert res_data["process_count"] == 120
    assert res_data["alert_triggered"] is False


@patch("main.get_server_by_token", return_value=None)
def test_ingest_metrics_endpoint_invalid_token(mock_get_server):
    from main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post(
        "/api/metrics",
        headers={"Authorization": "Bearer invalid-token"},
        json={"cpu_usage": 10.0, "ram_usage": 20.0, "network_traffic": 5.0},
    )
    if response.status_code != 401:
        print("TEST ERROR BODY 2:", response.json())

    assert response.status_code == 401
    assert "Invalid or missing ingestion token" in response.json()["detail"]


