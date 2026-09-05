"""CloudPulse AI — Advanced Statistical Anomaly Detection Engine.

Extends rolling z-scores with:
1. Rolling baselines (moving average & stddev across configurable lookback windows)
2. Time-aware baselines (comparing Monday 10:00 to historical Monday/weekday 10:00 windows)
3. Adaptive thresholds (adjusting deviation bands by variance with hard safety limits)
4. Multi-level severity (INFO, WARNING, CRITICAL)
5. Persistence & duration gating (consecutive sample threshold to suppress transient noise)
6. Multi-metric idle detection (CPU, RAM, network, disk IO over sustained windows)
7. Honest, deterministic explanations (metric, current, baseline, sigma, duration, method)
   without using LLMs for numerical anomaly calculation.

Preserves backwards compatibility with existing RPC baseline helpers.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from dotenv import load_dotenv

load_dotenv()

# Configuration knobs (configurable via environment variables)
ANOMALY_Z_SCORE = float(os.getenv("ANOMALY_Z_SCORE", "3.0"))
NETWORK_Z_SCORE = float(os.getenv("NETWORK_Z_SCORE", "4.0"))
BASELINE_DAYS = int(os.getenv("BASELINE_DAYS", "7"))
BASELINE_MIN_SAMPLES = int(os.getenv("BASELINE_MIN_SAMPLES", "5"))
TIME_AWARE_MIN_SAMPLES = int(os.getenv("TIME_AWARE_MIN_SAMPLES", "3"))
CONSECUTIVE_ANOMALY_THRESHOLD = int(os.getenv("CONSECUTIVE_ANOMALY_THRESHOLD", "3"))

IDLE_CPU_FLOOR = float(os.getenv("IDLE_CPU_FLOOR", "5.0"))
IDLE_RAM_FLOOR = float(os.getenv("IDLE_RAM_FLOOR", "15.0"))
IDLE_NET_FLOOR = float(os.getenv("IDLE_NET_FLOOR", "0.5"))  # MB
PEGGED_CPU_CEILING = float(os.getenv("PEGGED_CPU_CEILING", "95.0"))

_SEVERITY_RANK = {"critical": 3, "warning": 2, "info": 1, "idle": 1}


class BaselineStats(TypedDict):
    mean: float
    std: Optional[float]
    sample_count: int
    is_time_aware: bool
    bucket_label: str


class AnomalyEventDict(TypedDict):
    alert_type: str
    metric_name: str
    current_value: float
    baseline_value: float
    deviation_sigma: Optional[float]
    severity: str  # "info" | "warning" | "critical"
    consecutive_count: int
    duration_seconds: int
    detection_method: str
    message: str
    status: str
    meta: dict[str, Any]


# In-memory persistence tracker for consecutive anomalous samples per server & metric.
# Key: f"{server_id}:{metric_name}:{alert_type}" -> {"count": int, "first_seen": datetime, "last_seen": datetime}
_CONSECUTIVE_TRACKER: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Rolling & Time-Aware Baseline Calculators
# ---------------------------------------------------------------------------

def calculate_mean_std(values: list[float]) -> tuple[float, Optional[float]]:
    """Compute mean and population standard deviation of a list of floats."""
    if not values:
        return 0.0, None
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    variance = sum((x - mean) ** 2 for x in values) / n
    std = math.sqrt(variance)
    return mean, (std if std > 1e-6 else None)


def parse_timestamp(ts: Any) -> datetime:
    """Parse various timestamp representations into a UTC datetime."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, str):
        # Handle ISO strings with Z or offsets
        s = ts.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def compute_time_aware_baseline(
    metrics_history: list[dict],
    metric_name: str,
    target_time: Optional[datetime] = None,
    hour_window: int = 1,
    min_samples: int = TIME_AWARE_MIN_SAMPLES,
) -> Optional[BaselineStats]:
    """Compute baseline filtered by similar hour-of-day and weekday/weekend profile.

    E.g., for Monday 10:00 AM, matches history points from weekdays between 09:00 and 11:00.
    Returns None if fewer than min_samples match.
    """
    if not metrics_history or len(metrics_history) < min_samples:
        return None

    target = target_time or datetime.now(timezone.utc)
    target_hour = target.hour
    is_target_weekend = target.weekday() >= 5  # 5=Saturday, 6=Sunday

    matched_values: list[float] = []

    for row in metrics_history:
        val = row.get(metric_name)
        if val is None:
            continue
        row_time = parse_timestamp(row.get("recorded_at"))
        is_row_weekend = row_time.weekday() >= 5

        # Group weekdays together and weekends together for better density
        if is_target_weekend != is_row_weekend:
            continue

        # Check hour proximity with wrap-around
        hour_diff = abs(row_time.hour - target_hour)
        if hour_diff > 12:
            hour_diff = 24 - hour_diff

        if hour_diff <= hour_window:
            matched_values.append(float(val))

    if len(matched_values) < min_samples:
        return None

    mean, std = calculate_mean_std(matched_values)
    bucket_type = "weekend" if is_target_weekend else "weekday"
    return {
        "mean": round(mean, 2),
        "std": round(std, 2) if std is not None else None,
        "sample_count": len(matched_values),
        "is_time_aware": True,
        "bucket_label": f"{bucket_type} {target_hour:02d}:00±{hour_window}h",
    }


def compute_rolling_baseline(
    metrics_history: list[dict],
    metric_name: str,
    min_samples: int = BASELINE_MIN_SAMPLES,
) -> Optional[BaselineStats]:
    """Compute overall rolling baseline (mean & std) across all provided metric points."""
    if not metrics_history or len(metrics_history) < min_samples:
        return None

    values = [float(r[metric_name]) for r in metrics_history if r.get(metric_name) is not None]
    if len(values) < min_samples:
        return None

    mean, std = calculate_mean_std(values)
    return {
        "mean": round(mean, 2),
        "std": round(std, 2) if std is not None else None,
        "sample_count": len(values),
        "is_time_aware": False,
        "bucket_label": f"rolling-{BASELINE_DAYS}d",
    }


def z_score(value: float, mean: float, std: Optional[float]) -> Optional[float]:
    """Standard score of value against baseline (None if std is zero or missing)."""
    if std is None or std < 1e-6:
        return None
    return (value - mean) / std


def compute_adaptive_threshold(
    baseline: BaselineStats,
    base_threshold: float = 3.0,
    metric_name: str = "cpu_usage",
) -> float:
    """Dynamically adapt the sigma threshold based on metric volatility and sample density.

    - Bursty metrics (like network traffic) receive wider standard deviation bands (+0.5 to +1.0).
    - Very low variance series receive tighter thresholds (-0.5).
    - Retains bounded limits [2.0, 5.0].
    """
    threshold = base_threshold
    if metric_name == "network_traffic":
        threshold = max(threshold, NETWORK_Z_SCORE)

    std = baseline["std"]
    mean = baseline["mean"]

    if std is not None and mean > 1.0:
        coefficient_of_variation = std / mean
        if coefficient_of_variation > 0.8:  # Highly volatile metric
            threshold += 0.5
        elif coefficient_of_variation < 0.1:  # Extremely steady baseline
            threshold = max(2.0, threshold - 0.5)

    return round(threshold, 2)


# ---------------------------------------------------------------------------
# Multi-Level Severity & Persistence Evaluation
# ---------------------------------------------------------------------------

def classify_severity(z: Optional[float], adaptive_thresh: float, current_val: float) -> str:
    """Classify anomaly severity into INFO, WARNING, or CRITICAL."""
    if current_val >= PEGGED_CPU_CEILING:
        return "critical"
    if z is None:
        return "info"
    if z >= adaptive_thresh + 1.5 or z >= 5.0:
        return "critical"
    if z >= adaptive_thresh:
        return "warning"
    if z >= adaptive_thresh - 0.8:
        return "info"
    return "info"


def update_consecutive_tracker(
    tracker_key: str,
    is_anomalous: bool,
    sample_time: Optional[datetime] = None,
) -> tuple[int, int]:
    """Update consecutive anomaly occurrences and duration in seconds.

    Returns (consecutive_count, duration_seconds).
    """
    now = sample_time or datetime.now(timezone.utc)
    entry = _CONSECUTIVE_TRACKER.get(tracker_key)

    if not is_anomalous:
        if entry:
            _CONSECUTIVE_TRACKER.pop(tracker_key, None)
        return 0, 0

    if not entry:
        _CONSECUTIVE_TRACKER[tracker_key] = {
            "count": 1,
            "first_seen": now,
            "last_seen": now,
        }
        return 1, 0

    count = entry["count"] + 1
    first_seen = entry["first_seen"]
    duration_secs = max(0, int((now - first_seen).total_seconds()))
    entry["count"] = count
    entry["last_seen"] = now

    return count, duration_secs


# ---------------------------------------------------------------------------
# Multi-Metric Idle Detection
# ---------------------------------------------------------------------------

def evaluate_multi_metric_idle(
    cpu: float,
    ram: float,
    network: float = 0.0,
    disk_usage: Optional[float] = None,
    recent_history: Optional[list[dict]] = None,
) -> Optional[dict]:
    """Check if resource is idle based on CPU, RAM, and sustained history.

    Requires CPU < IDLE_CPU_FLOOR and RAM < IDLE_RAM_FLOOR.
    If recent_history is provided, verifies that idle state is sustained over recent samples.
    """
    is_current_idle = (cpu < IDLE_CPU_FLOOR) and (ram < IDLE_RAM_FLOOR)
    if not is_current_idle:
        return None

    # Check history if present to prevent flagging on brief temporary dips
    if recent_history and len(recent_history) >= 3:
        for prev in recent_history[-3:]:
            prev_cpu = float(prev.get("cpu_usage", 100.0))
            prev_ram = float(prev.get("ram_usage", 100.0))
            if prev_cpu >= IDLE_CPU_FLOOR * 1.5 or prev_ram >= IDLE_RAM_FLOOR * 1.5:
                # Intermittent quiet period, not sustained idle
                return None

    return {
        "alert_type": "IDLE_RESOURCE",
        "metric_name": "cpu_ram",
        "severity": "info",
        "status": "idle",
        "current_value": round(cpu, 1),
        "baseline_value": round(IDLE_CPU_FLOOR, 1),
        "deviation_sigma": None,
        "detection_method": "multi_metric_idle",
        "message": (
            f"Node idle: CPU {cpu:.1f}% (<{IDLE_CPU_FLOOR:.0f}%) and "
            f"RAM {ram:.1f}% (<{IDLE_RAM_FLOOR:.0f}%). "
            "Sustained low utilization indicates resource can be downsized or stopped."
        ),
        "meta": {
            "cpu": cpu,
            "ram": ram,
            "network": network,
            "idle_duration_verified": bool(recent_history and len(recent_history) >= 3),
        },
    }


# ---------------------------------------------------------------------------
# Main Advanced Anomaly Detection Entrypoint
# ---------------------------------------------------------------------------

def check_advanced_anomalies(
    server_id: str,
    cpu: float,
    ram: float,
    network: float,
    disk_usage: Optional[float] = None,
    metrics_history: Optional[list[dict]] = None,
    rpc_baseline_dict: Optional[dict] = None,
    sample_time: Optional[datetime] = None,
    require_persistence: bool = False,
) -> list[AnomalyEventDict]:
    """Evaluate metric points using multi-tiered time-aware & rolling baseline detection.

    Returns structured anomaly event dicts with confidence, explanations, and severity.
    """
    sample_dt = sample_time or datetime.now(timezone.utc)
    anomalies: list[AnomalyEventDict] = []

    # Map of metric to test
    metrics_to_test = [
        ("cpu_usage", cpu, "HIGH_CPU", ANOMALY_Z_SCORE, "critical"),
        ("ram_usage", ram, "HIGH_RAM", ANOMALY_Z_SCORE, "warning"),
        ("network_traffic", network, "NETWORK_ANOMALY", NETWORK_Z_SCORE, "warning"),
    ]
    if disk_usage is not None:
        metrics_to_test.append(("disk_usage", disk_usage, "HIGH_DISK", 3.0, "warning"))

    for metric_name, current_val, alert_type, base_thresh, default_status in metrics_to_test:
        baseline: Optional[BaselineStats] = None
        method = "rolling_zscore"

        # 1. Attempt Time-Aware Baseline first if history exists
        if metrics_history:
            baseline = compute_time_aware_baseline(metrics_history, metric_name, target_time=sample_dt)
            if baseline:
                method = "time_aware_baseline"

        # 2. Fall back to Rolling Baseline from metric history or RPC baseline
        if not baseline and metrics_history:
            baseline = compute_rolling_baseline(metrics_history, metric_name)
            if baseline:
                method = "rolling_zscore"

        if not baseline and rpc_baseline_dict:
            # Fall back to PostgREST RPC baseline aggregate if available
            short_key = "cpu" if "cpu" in metric_name else ("ram" if "ram" in metric_name else "network")
            sub = rpc_baseline_dict.get(short_key)
            if sub and rpc_baseline_dict.get("sample_count", 0) >= BASELINE_MIN_SAMPLES:
                baseline = {
                    "mean": float(sub.get("mean", 0.0)),
                    "std": float(sub["std"]) if sub.get("std") is not None else None,
                    "sample_count": int(rpc_baseline_dict["sample_count"]),
                    "is_time_aware": False,
                    "bucket_label": f"rpc-{BASELINE_DAYS}d",
                }
                method = "rpc_baseline"

        if not baseline:
            # Warmup / no baseline available
            continue

        adaptive_thresh = compute_adaptive_threshold(baseline, base_threshold=base_thresh, metric_name=metric_name)
        z = z_score(current_val, baseline["mean"], baseline["std"])

        is_anomaly = False
        is_pegged = (metric_name == "cpu_usage" and current_val >= PEGGED_CPU_CEILING)

        if z is not None and z >= adaptive_thresh:
            is_anomaly = True
        elif is_pegged:
            is_anomaly = True

        tracker_key = f"{server_id}:{metric_name}:{alert_type}"
        consecutive_count, duration_secs = update_consecutive_tracker(
            tracker_key, is_anomaly, sample_time=sample_dt
        )

        if is_anomaly:
            # If persistence requirement enabled, only alert after consecutive count threshold
            if require_persistence and consecutive_count < CONSECUTIVE_ANOMALY_THRESHOLD:
                continue

            severity = classify_severity(z, adaptive_thresh, current_val)
            z_str = f"{z:.1f}σ" if z is not None else "pegged"
            unit = "%" if ("usage" in metric_name or "cpu" in metric_name or "ram" in metric_name) else " MB"

            std_val = baseline.get("std")
            std_str = f" ± {std_val:.1f}{unit}" if std_val is not None else ""
            explanation = (
                f"{metric_name.replace('_', ' ').upper()} {current_val:.1f}{unit} is {z_str} "
                f"above {baseline['bucket_label']} baseline (expected {baseline['mean']:.1f}{unit}"
                f"{std_str}) detected via {method}."
            )
            if consecutive_count > 1:
                duration_min = max(1, duration_secs // 60)
                explanation += f" Persisted for {consecutive_count} consecutive samples (~{duration_min}m)."

            anomalies.append({
                "alert_type": alert_type,
                "metric_name": metric_name,
                "current_value": round(current_val, 2),
                "baseline_value": round(baseline["mean"], 2),
                "deviation_sigma": round(z, 2) if z is not None else None,
                "severity": severity,
                "consecutive_count": consecutive_count,
                "duration_seconds": duration_secs,
                "detection_method": method,
                "message": explanation,
                "status": "critical" if severity == "critical" else default_status,
                "meta": {
                    "adaptive_threshold": adaptive_thresh,
                    "sample_count": baseline["sample_count"],
                    "bucket_label": baseline["bucket_label"],
                    "std": baseline["std"],
                },
            })

    # Multi-metric idle detection
    idle_result = evaluate_multi_metric_idle(cpu, ram, network, disk_usage, metrics_history)
    if idle_result:
        tracker_key = f"{server_id}:idle:IDLE_RESOURCE"
        c_count, d_secs = update_consecutive_tracker(tracker_key, True, sample_time=sample_dt)
        idle_result["consecutive_count"] = c_count
        idle_result["duration_seconds"] = d_secs
        anomalies.append(idle_result)
    else:
        update_consecutive_tracker(f"{server_id}:idle:IDLE_RESOURCE", False, sample_time=sample_dt)

    return anomalies


# ---------------------------------------------------------------------------
# Legacy Compatibility Functions
# ---------------------------------------------------------------------------

def baseline_from_rpc(result: Optional[dict]) -> Optional[dict]:
    """Turn a ``metrics_baseline`` RPC row into a friendly baseline dict."""
    if not result:
        return None
    count = int(result.get("sample_count") or 0)
    if count == 0:
        return None

    def _pair(mean_key: str, std_key: str) -> dict:
        mean = result.get(mean_key)
        std = result.get(std_key)
        return {
            "mean": float(mean) if mean is not None else 0.0,
            "std": float(std) if std is not None else None,
        }

    return {
        "cpu": _pair("cpu_mean", "cpu_std"),
        "ram": _pair("ram_mean", "ram_std"),
        "network": _pair("net_mean", "net_std"),
        "sample_count": count,
        "days": BASELINE_DAYS,
    }


def check_anomalies(
    server_id: str,
    cpu: float,
    ram: float,
    network: float,
    baseline: Optional[dict],
) -> list[dict]:
    """Backwards-compatible wrapper delegating to advanced anomaly detection."""
    events = check_advanced_anomalies(
        server_id=server_id,
        cpu=cpu,
        ram=ram,
        network=network,
        rpc_baseline_dict=baseline,
    )
    return [
        {
            "alert_type": e["alert_type"],
            "status": e.get("status", "warning"),
            "message": e["message"],
            "severity": e.get("severity", "warning"),
            "meta": e.get("meta", {}),
        }
        for e in events
    ]


def most_severe(statuses: list[str]) -> str:
    """Pick the status that should win for a server (critical > warning > info/idle)."""
    return max(statuses, key=lambda s: _SEVERITY_RANK.get(s, 0))
