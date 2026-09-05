"""Deterministic unit tests for the Advanced Anomaly Detection Engine (Phase 2).

Tests:
- Rolling baseline computation
- Time-aware baseline computation (hour-of-day / weekday profile)
- Adaptive threshold adaptation
- Multi-level severity classification (INFO, WARNING, CRITICAL)
- Consecutive sample persistence gating
- Multi-metric idle detection (CPU, RAM, network, disk)
- Structured numerical explanations
"""

from datetime import datetime, timezone, timedelta
from anomaly import (
    calculate_mean_std,
    compute_rolling_baseline,
    compute_time_aware_baseline,
    compute_adaptive_threshold,
    classify_severity,
    evaluate_multi_metric_idle,
    check_advanced_anomalies,
    update_consecutive_tracker,
    _CONSECUTIVE_TRACKER,
)


def _generate_synthetic_history(
    count=20,
    base_cpu=25.0,
    base_ram=40.0,
    base_net=100.0,
    start_hour=10,
    is_weekday=True,
):
    """Generate synthetic telemetry rows with deterministic timestamps."""
    history = []
    # Monday (weekday) vs Sunday (weekend)
    base_date = datetime(2026, 9, 7, start_hour, 0, tzinfo=timezone.utc) if is_weekday else datetime(2026, 9, 6, start_hour, 0, tzinfo=timezone.utc)

    for i in range(count):
        # Step back in 7-day intervals (same day of week) or small minute increments
        dt = base_date - timedelta(days=7 * (i % 4), minutes=5 * (i // 4))
        history.append({
            "cpu_usage": base_cpu + (i % 3) - 1.0,  # e.g. 24, 25, 26
            "ram_usage": base_ram + (i % 2) - 0.5,
            "network_traffic": base_net + (i % 5) * 2.0,
            "disk_usage": 35.0,
            "recorded_at": dt.isoformat(),
        })
    return history


def test_calculate_mean_std():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    mean, std = calculate_mean_std(vals)
    assert mean == 30.0
    assert std is not None
    assert round(std, 2) == 14.14


def test_calculate_mean_std_constant_series():
    vals = [42.0, 42.0, 42.0]
    mean, std = calculate_mean_std(vals)
    assert mean == 42.0
    assert std is None  # Zero spread is represented as None


def test_rolling_baseline():
    history = _generate_synthetic_history(count=15, base_cpu=30.0)
    baseline = compute_rolling_baseline(history, "cpu_usage", min_samples=5)
    assert baseline is not None
    assert baseline["is_time_aware"] is False
    assert 29.0 <= baseline["mean"] <= 31.0
    assert baseline["sample_count"] == 15


def test_time_aware_baseline_matches_hour_and_weekday():
    history = _generate_synthetic_history(count=20, base_cpu=20.0, start_hour=10, is_weekday=True)
    # Target is Monday 10:30 UTC
    target_dt = datetime(2026, 9, 7, 10, 30, tzinfo=timezone.utc)
    baseline = compute_time_aware_baseline(history, "cpu_usage", target_time=target_dt, hour_window=1)
    assert baseline is not None
    assert baseline["is_time_aware"] is True
    assert "weekday" in baseline["bucket_label"]
    assert "10:00" in baseline["bucket_label"]
    assert 19.0 <= baseline["mean"] <= 21.0


def test_time_aware_baseline_insufficient_matches_returns_none():
    # History is all Sunday (weekend)
    history = _generate_synthetic_history(count=10, base_cpu=20.0, start_hour=10, is_weekday=False)
    # Target is Monday (weekday)
    target_dt = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
    baseline = compute_time_aware_baseline(history, "cpu_usage", target_time=target_dt, min_samples=3)
    assert baseline is None


def test_adaptive_threshold_high_volatility():
    baseline = {
        "mean": 10.0,
        "std": 12.0,  # std / mean = 1.2 > 0.8
        "sample_count": 50,
        "is_time_aware": False,
        "bucket_label": "rolling",
    }
    thresh = compute_adaptive_threshold(baseline, base_threshold=3.0, metric_name="cpu_usage")
    assert thresh == 3.5  # Wider band for high volatility


def test_adaptive_threshold_steady_baseline():
    baseline = {
        "mean": 80.0,
        "std": 2.0,  # std / mean = 0.025 < 0.1
        "sample_count": 50,
        "is_time_aware": False,
        "bucket_label": "rolling",
    }
    thresh = compute_adaptive_threshold(baseline, base_threshold=3.0, metric_name="cpu_usage")
    assert thresh == 2.5  # Tighter band for steady baseline


def test_classify_severity():
    assert classify_severity(z=5.5, adaptive_thresh=3.0, current_val=80.0) == "critical"
    assert classify_severity(z=3.4, adaptive_thresh=3.0, current_val=60.0) == "warning"
    assert classify_severity(z=2.4, adaptive_thresh=3.0, current_val=40.0) == "info"
    assert classify_severity(z=None, adaptive_thresh=3.0, current_val=98.0) == "critical"  # Pegged


def test_multi_metric_idle_detection():
    # Idle across CPU, RAM, Network
    idle = evaluate_multi_metric_idle(cpu=2.1, ram=8.5, network=0.1)
    assert idle is not None
    assert idle["alert_type"] == "IDLE_RESOURCE"
    assert idle["status"] == "idle"
    assert "Node idle" in idle["message"]

    # Not idle if CPU is elevated
    not_idle_cpu = evaluate_multi_metric_idle(cpu=12.0, ram=8.5, network=0.1)
    assert not_idle_cpu is None

    # Not idle if RAM is elevated
    not_idle_ram = evaluate_multi_metric_idle(cpu=2.0, ram=45.0, network=0.1)
    assert not_idle_ram is None


def test_check_advanced_anomalies_time_aware_spike():
    _CONSECUTIVE_TRACKER.clear()
    history = _generate_synthetic_history(count=20, base_cpu=20.0, start_hour=10, is_weekday=True)
    target_dt = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    # Normal point should yield no anomalies
    res_normal = check_advanced_anomalies(
        server_id="test-srv-1",
        cpu=21.0,
        ram=40.0,
        network=100.0,
        metrics_history=history,
        sample_time=target_dt,
    )
    assert len(res_normal) == 0

    # Large spike (e.g. CPU 85%) should trigger HIGH_CPU with structured explanation
    res_spike = check_advanced_anomalies(
        server_id="test-srv-1",
        cpu=85.0,
        ram=40.0,
        network=100.0,
        metrics_history=history,
        sample_time=target_dt,
    )
    assert len(res_spike) >= 1
    cpu_anomaly = next(a for a in res_spike if a["alert_type"] == "HIGH_CPU")
    assert cpu_anomaly["severity"] in ("warning", "critical")
    assert cpu_anomaly["detection_method"] == "time_aware_baseline"
    assert "time_aware_baseline" in cpu_anomaly["message"]
    assert cpu_anomaly["current_value"] == 85.0
    assert cpu_anomaly["deviation_sigma"] is not None
    assert cpu_anomaly["deviation_sigma"] > 5.0


def test_persistence_gating():
    _CONSECUTIVE_TRACKER.clear()
    history = _generate_synthetic_history(count=20, base_cpu=20.0, start_hour=10, is_weekday=True)
    target_dt = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    # 1st sample: should be filtered out when require_persistence=True
    res_1 = check_advanced_anomalies(
        server_id="persist-srv",
        cpu=80.0,
        ram=40.0,
        network=100.0,
        metrics_history=history,
        sample_time=target_dt,
        require_persistence=True,
    )
    assert len(res_1) == 0

    # 2nd sample
    res_2 = check_advanced_anomalies(
        server_id="persist-srv",
        cpu=80.0,
        ram=40.0,
        network=100.0,
        metrics_history=history,
        sample_time=target_dt + timedelta(minutes=5),
        require_persistence=True,
    )
    assert len(res_2) == 0

    # 3rd consecutive sample triggers persistent alert
    res_3 = check_advanced_anomalies(
        server_id="persist-srv",
        cpu=80.0,
        ram=40.0,
        network=100.0,
        metrics_history=history,
        sample_time=target_dt + timedelta(minutes=10),
        require_persistence=True,
    )
    assert len(res_3) >= 1
    assert res_3[0]["consecutive_count"] == 3
    assert "Persisted for 3 consecutive samples" in res_3[0]["message"]
