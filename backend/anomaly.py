"""CloudPulse AI — statistical anomaly detection.

Replaces the old hardcoded thresholds (CPU > 85, network > 500, …) with a
**rolling baseline**: per server, per metric, the last N days of telemetry are
summarized as a mean + population stddev, and the latest point is flagged when
its **z-score** exceeds a threshold. This is statistics, not ML — there is no
trained model anywhere; the "AI" that summarizes alerts lives in ``insights.py``
and only reads the output of this module.

Honest limits (intentional):
- **Warmup**: a server needs >= ``BASELINE_MIN_SAMPLES`` points in the window
  before any z-score claim is made. With no baseline we stay silent.
- **Constant series**: if stddev ≈ 0 there is no spread to measure a z-score
  against; we only flag a metric pegged at the physical ceiling (CPU 100%).
- **Idle is NOT an anomaly**: a chronically idle node has a flat, already-low
  baseline, so z-scores can't detect it. IDLE_RESOURCE therefore uses absolute
  low-utilization *floors* (a low-watermark state signal, not a cutoff).

Env knobs (see .env.example):
    ANOMALY_Z_SCORE=3.0        z threshold for HIGH_CPU
    NETWORK_Z_SCORE=4.0        z threshold for NETWORK_ANOMALY (bursty metric)
    BASELINE_DAYS=7            rolling window length
    BASELINE_MIN_SAMPLES=10    warmup gate
    IDLE_CPU_FLOOR=5.0         idle = cpu below this AND …
    IDLE_RAM_FLOOR=10.0        … ram below this
    PEGGED_CPU_CEILING=99.0    std≈0 HIGH_CPU guard
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

ANOMALY_Z_SCORE = float(os.getenv("ANOMALY_Z_SCORE", "3.0"))
NETWORK_Z_SCORE = float(os.getenv("NETWORK_Z_SCORE", "4.0"))
BASELINE_DAYS = int(os.getenv("BASELINE_DAYS", "7"))
BASELINE_MIN_SAMPLES = int(os.getenv("BASELINE_MIN_SAMPLES", "10"))
IDLE_CPU_FLOOR = float(os.getenv("IDLE_CPU_FLOOR", "5.0"))
IDLE_RAM_FLOOR = float(os.getenv("IDLE_RAM_FLOOR", "10.0"))
PEGGED_CPU_CEILING = float(os.getenv("PEGGED_CPU_CEILING", "99.0"))

# Severity ordering for status updates (most severe wins).
_SEVERITY_RANK = {"critical": 3, "warning": 2, "idle": 1}

# Metrics we carry a baseline for, and the latest sample key for each.
_METRICS = {
    "cpu": "cpu_usage",
    "ram": "ram_usage",
    "network": "network_traffic",
}


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

def baseline_from_rpc(result: Optional[dict]) -> Optional[dict]:
    """Turn a ``metrics_baseline`` RPC row into a friendly baseline dict.

    The Postgres aggregate returns a single row even for an empty window (all
    NULLs). Returns ``None`` when the window is empty or the result is missing.

    Return shape::

        {
            "cpu":     {"mean": float, "std": float | None},
            "ram":     {"mean": float, "std": float | None},
            "network": {"mean": float, "std": float | None},
            "sample_count": int,
            "days": int,
        }

    ``std`` is ``None`` when the series is constant (stddev_pop = 0 → treated as
    "no spread to measure against").
    """
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


def z_score(value: float, mean: float, std: Optional[float]) -> Optional[float]:
    """Standard score of ``value`` against a baseline (None when no spread)."""
    if std is None or std < 1e-9:
        return None
    return (value - mean) / std


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def check_anomalies(
    server_id: str,
    cpu: float,
    ram: float,
    network: float,
    baseline: Optional[dict],
) -> list[dict]:
    """Evaluate the latest sample against a rolling baseline.

    Returns a list of ``{alert_type, message, status}`` dicts (empty when no
    anomaly is justified). Callers insert each alert and apply the most severe
    status via :func:`most_severe`.

    A ``None`` baseline (warmup / missing RPC) yields no anomaly claims.
    """
    if baseline is None:
        return []

    alerts: list[dict] = []
    if baseline["sample_count"] < BASELINE_MIN_SAMPLES:
        # Insufficient baseline — stay silent rather than mislabel noise.
        return []

    # --- HIGH_CPU ---
    cpu_std = baseline["cpu"]["std"]
    cpu_z = z_score(cpu, baseline["cpu"]["mean"], cpu_std)
    if cpu_z is not None and cpu_z > ANOMALY_Z_SCORE:
        alerts.append({
            "alert_type": "HIGH_CPU",
            "status": "critical",
            "message": (
                f"CPU {cpu:.1f}% is {cpu_z:.1f}σ above the {BASELINE_DAYS}-day baseline "
                f"(mean {baseline['cpu']['mean']:.1f}%, σ {cpu_std:.1f}%) — check for a "
                "runaway process or load imbalance."
            ),
        })
    elif cpu_z is None and cpu >= PEGGED_CPU_CEILING:
        # Constant series pinned at 100% is still an anomaly worth surfacing.
        alerts.append({
            "alert_type": "HIGH_CPU",
            "status": "critical",
            "message": (
                f"CPU is pegged at {cpu:.1f}% with a flat baseline — sustained saturation "
                "requires intervention."
            ),
        })

    # --- NETWORK_ANOMALY ---
    net_std = baseline["network"]["std"]
    net_z = z_score(network, baseline["network"]["mean"], net_std)
    if net_z is not None and net_z > NETWORK_Z_SCORE:
        alerts.append({
            "alert_type": "NETWORK_ANOMALY",
            "status": "warning",
            "message": (
                f"Network {network:.2f} MB is {net_z:.1f}σ above the {BASELINE_DAYS}-day "
                f"baseline (mean {baseline['network']['mean']:.2f} MB, σ {net_std:.2f} MB) — "
                "investigate possible data exfiltration or an unexpected workload."
            ),
        })

    # --- IDLE_RESOURCE (absolute low-watermark, not an anomaly) ---
    if cpu < IDLE_CPU_FLOOR and ram < IDLE_RAM_FLOOR:
        alerts.append({
            "alert_type": "IDLE_RESOURCE",
            "status": "idle",
            "message": (
                f"Node idle — CPU {cpu:.1f}% / RAM {ram:.1f}% are below the "
                f"{IDLE_CPU_FLOOR:.0f}%/{IDLE_RAM_FLOOR:.0f}% floors. "
                "Consider downsizing or shutting down."
            ),
        })

    return alerts


def most_severe(statuses: list[str]) -> str:
    """Pick the status that should win for a server (critical > warning > idle).

    If nothing was flagged, the server is left in its current state (callers
    only update when at least one alert exists).
    """
    return max(statuses, key=lambda s: _SEVERITY_RANK.get(s, 0))
