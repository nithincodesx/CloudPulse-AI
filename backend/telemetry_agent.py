#!/usr/bin/env python3
"""CloudPulse AI — Telemetry Agent

Captures real-time host metrics via psutil and pushes them to the
FastAPI backend at a configurable interval.

Usage:
    python telemetry_agent.py --token <INGESTION_TOKEN> [--interval 5] [--api-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import time
from typing import NoReturn

import psutil
import httpx


# ---------------------------------------------------------------------------
# Metric collection
# ---------------------------------------------------------------------------

def collect_metrics() -> dict:
    """Return a snapshot of current host metrics."""
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory().percent
    net = psutil.net_io_counters()
    network_mb = (net.bytes_sent + net.bytes_recv) / (1024 * 1024)

    # Simple cost heuristic: ~$0.01 per 1% CPU-hour baseline
    estimated_cost = round(cpu * 0.0001 * (ram / 100), 6)

    return {
        "cpu_usage": round(cpu, 1),
        "ram_usage": round(ram, 1),
        "network_traffic": round(network_mb, 2),
        "estimated_cost_per_hour": estimated_cost,
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_agent(token: str, api_url: str, interval: int) -> NoReturn:
    """Continuously collect and push metrics, authenticating with a bearer token."""
    print(f"[CloudPulse Agent] Token:      {token[:12]}… (server identified by token)")
    print(f"[CloudPulse Agent] API:        {api_url}/api/metrics")
    print(f"[CloudPulse Agent] Interval:   {interval}s")
    print("-" * 56)

    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(base_url=api_url, timeout=10, headers=headers) as client:
        while True:
            try:
                metrics = collect_metrics()

                resp = client.post("/api/metrics", json=metrics)
                resp.raise_for_status()
                data = resp.json()

                alert_flag = "[ALERT]" if data.get("alert_triggered") else ""
                print(
                    f"[{time.strftime('%H:%M:%S')}] "
                    f"CPU {metrics['cpu_usage']:5.1f}% | "
                    f"RAM {metrics['ram_usage']:5.1f}% | "
                    f"Net {metrics['network_traffic']:6.2f} MB | "
                    f"$ {metrics['estimated_cost_per_hour']:.6f}/h"
                    f"{alert_flag}"
                )

            except httpx.ConnectError:
                print(f"[{time.strftime('%H:%M:%S')}] [ERROR] Cannot reach {api_url}")
            except httpx.HTTPStatusError as exc:
                print(f"[{time.strftime('%H:%M:%S')}] [ERROR] {exc.response.status_code}: {exc.response.text}")
            except Exception as exc:
                print(f"[{time.strftime('%H:%M:%S')}] [ERROR] {exc}")

            time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CloudPulse AI Telemetry Agent")
    parser.add_argument(
        "--token",
        required=True,
        help="Ingestion token of the server node (from the CloudPulse UI or the servers table)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Collection interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="FastAPI base URL (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    try:
        run_agent(args.token, args.api_url, args.interval)
    except KeyboardInterrupt:
        print("\n[CloudPulse Agent] Shutting down.")
