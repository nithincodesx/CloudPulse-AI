"""Unit tests for the statistical anomaly detector (backend/anomaly.py).

Pure logic only — no database, no LLM, no AWS. Tests that need real Supabase /
LLM / AWS credentials are intentionally excluded from CI (they require secrets).
"""

from anomaly import (
    baseline_from_rpc,
    check_anomalies,
    most_severe,
    z_score,
)


def _baseline(**overrides):
    """A normal 500-sample baseline; tweak fields per test."""
    row = {
        "cpu_mean": 40.0, "cpu_std": 10.0,
        "ram_mean": 50.0, "ram_std": 5.0,
        "net_mean": 200.0, "net_std": 50.0,
        "sample_count": 500,
    }
    row.update(overrides)
    return baseline_from_rpc(row)


def _types(alerts):
    return [a["alert_type"] for a in alerts]


# --- baseline_from_rpc -------------------------------------------------------

def test_baseline_from_rpc_parses_row():
    b = _baseline()
    assert b["sample_count"] == 500
    assert b["cpu"] == {"mean": 40.0, "std": 10.0}
    assert b["network"] == {"mean": 200.0, "std": 50.0}
    assert b["days"] == 7


def test_baseline_from_rpc_empty_or_missing_returns_none():
    assert baseline_from_rpc(None) is None
    assert baseline_from_rpc({}) is None
    assert baseline_from_rpc({"cpu_mean": None, "sample_count": 0}) is None


def test_baseline_from_rpc_null_std_is_none():
    b = baseline_from_rpc({
        "cpu_mean": 50.0, "cpu_std": None,
        "ram_mean": 50.0, "ram_std": 5.0,
        "net_mean": 200.0, "net_std": 50.0,
        "sample_count": 100,
    })
    assert b["cpu"]["std"] is None
    assert b["cpu"]["mean"] == 50.0


# --- z_score -----------------------------------------------------------------

def test_z_score_standard():
    assert z_score(94, 40, 10) == 5.4


def test_z_score_zero_std_is_none():
    assert z_score(80, 40, 0.0) is None
    assert z_score(80, 40, None) is None


# --- check_anomalies ---------------------------------------------------------

def test_warmup_requires_min_samples():
    b = _baseline(sample_count=3)
    assert check_anomalies("s1", cpu=99, ram=90, network=9999, baseline=b) == []


def test_no_baseline_yields_no_claims():
    assert check_anomalies("s1", 99, 90, 9999, baseline=None) == []


def test_high_cpu_via_z_score():
    alerts = check_anomalies("s1", cpu=94, ram=30, network=210, baseline=_baseline())
    assert "HIGH_CPU" in _types(alerts)
    assert next(a for a in alerts if a["alert_type"] == "HIGH_CPU")["status"] == "critical"
    assert "σ" in next(a for a in alerts if a["alert_type"] == "HIGH_CPU")["message"]


def test_normal_load_no_alerts():
    assert check_anomalies("s1", cpu=41, ram=49, network=210, baseline=_baseline()) == []


def test_network_anomaly_needs_stricter_z():
    # +6.0σ network → flagged; but a +3.5σ network is below NETWORK_Z_SCORE(4.0).
    b = _baseline()
    alerts = check_anomalies("s1", cpu=40, ram=50, network=500, baseline=b)  # +6σ
    assert "NETWORK_ANOMALY" in _types(alerts)
    alerts = check_anomalies("s1", cpu=40, ram=50, network=375, baseline=b)  # +3.5σ
    assert "NETWORK_ANOMALY" not in _types(alerts)


def test_idle_floors():
    alerts = check_anomalies("s1", cpu=2, ram=5, network=100, baseline=_baseline())
    assert _types(alerts) == ["IDLE_RESOURCE"]
    assert alerts[0]["status"] == "idle"


def test_pegged_cpu_on_flat_baseline_flagged():
    b = _baseline(cpu_mean=99.0, cpu_std=0.0)
    alerts = check_anomalies("s1", cpu=99.8, ram=30, network=210, baseline=b)
    assert "HIGH_CPU" in _types(alerts)


def test_null_std_no_high_cpu():
    b = baseline_from_rpc({
        "cpu_mean": 50.0, "cpu_std": None,
        "ram_mean": 50.0, "ram_std": 5.0,
        "net_mean": 200.0, "net_std": 50.0,
        "sample_count": 100,
    })
    alerts = check_anomalies("s1", cpu=80, ram=30, network=210, baseline=b)
    assert "HIGH_CPU" not in _types(alerts)


def test_multiple_anomalies_can_coexist():
    b = _baseline()
    alerts = check_anomalies("s1", cpu=2, ram=5, network=800, baseline=b)  # idle + net spike
    assert set(_types(alerts)) == {"IDLE_RESOURCE", "NETWORK_ANOMALY"}


# --- most_severe -------------------------------------------------------------

def test_most_severe_precedence():
    assert most_severe(["idle", "critical", "warning"]) == "critical"
    assert most_severe(["idle", "warning"]) == "warning"
    assert most_severe(["idle"]) == "idle"
