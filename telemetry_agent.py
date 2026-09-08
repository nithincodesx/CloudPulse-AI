#!/usr/bin/env python3
"""CloudPulse AI — Enterprise Telemetry Agent

Captures real-time host metrics via psutil (CPU, RAM, Disk, Network, Uptime, I/O)
and pushes them to the CloudPulse FastAPI backend with token-based bearer authentication.

Cross-platform compatible with native support for Windows, Linux, and macOS.

Usage:
    python telemetry_agent.py --token <INGESTION_TOKEN> [--url http://localhost:8000] [--interval 5]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

try:
    import psutil
except ImportError:
    print("[ERROR] psutil is not installed. Run: pip install psutil")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("[ERROR] httpx is not installed. Run: pip install httpx")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Metric Collection Engine (Cross-Platform / Windows Compatible)
# ---------------------------------------------------------------------------

def collect_metrics() -> dict[str, Any]:
    """Capture host telemetry safely across Windows and POSIX systems."""
    # 1. CPU Usage (sampled over a brief non-blocking interval)
    cpu = psutil.cpu_percent(interval=0.5)

    # 2. RAM Usage
    vmem = psutil.virtual_memory()
    ram = vmem.percent

    # 3. Network Traffic (cumulative MB transferred)
    try:
        net = psutil.net_io_counters()
        network_mb = (net.bytes_sent + net.bytes_recv) / (1024 * 1024)
    except Exception:
        net = None
        network_mb = 0.0

    metrics: dict[str, Any] = {
        "cpu_usage": round(cpu, 1),
        "ram_usage": round(ram, 1),
        "network_traffic": round(network_mb, 2),
    }

    # 4. Disk Usage (Windows drive path vs POSIX root)
    try:
        metrics["disk_usage"] = round(psutil.disk_usage("/").percent, 1)
    except Exception:
        try:
            # Fallback for Windows root
            drive = os.environ.get("SystemDrive", "C:") + "\\\\"
            metrics["disk_usage"] = round(psutil.disk_usage(drive).percent, 1)
        except Exception:
            metrics["disk_usage"] = 0.0

    # 5. Disk I/O Rates
    try:
        disk_io = psutil.disk_io_counters()
        if disk_io:
            metrics["disk_io"] = {
                "read_mb": round(disk_io.read_bytes / (1024 * 1024), 2),
                "write_mb": round(disk_io.write_bytes / (1024 * 1024), 2),
            }
    except Exception:
        pass

    # 6. System Uptime (seconds since boot)
    try:
        boot_time = psutil.boot_time()
        metrics["system_uptime"] = round(time.time() - boot_time, 1)
    except Exception:
        pass

    # 7. System Load Average (Unix only; safely omitted on Windows)
    if hasattr(os, "getloadavg"):
        try:
            metrics["load_average"] = [round(x, 2) for x in os.getloadavg()]
        except Exception:
            pass

    # 8. Process Count
    try:
        metrics["process_count"] = len(psutil.pids())
    except Exception:
        pass

    # 9. Detailed Network Stats
    if net:
        try:
            metrics["network_stats"] = {
                "packets_sent": getattr(net, "packets_sent", 0),
                "packets_recv": getattr(net, "packets_recv", 0),
                "errin": getattr(net, "errin", 0),
                "errout": getattr(net, "errout", 0),
            }
        except Exception:
            pass

    return metrics


# ---------------------------------------------------------------------------
# Telemetry Dispatcher Loop
# ---------------------------------------------------------------------------

def run_agent(token: str, api_url: str, interval: int) -> None:
    """Continuously push telemetry packets to CloudPulse backend with retry resilience."""
    clean_url = api_url.rstrip("/")
    masked_token = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"

    print("=" * 64)
    print("  CLOUDPULSE-AI ENTERPRISE TELEMETRY AGENT")
    print("=" * 64)
    print(f"  Target API:     {clean_url}/api/metrics")
    print(f"  Ingestion Key:  {masked_token}")
    print(f"  Sample Rate:    every {interval}s")
    print(f"  Platform:       {sys.platform.capitalize()} (psutil {psutil.__version__})")
    print("=" * 64)
    print("[INFO] Telemetry agent started. Streaming live metrics...")
    print()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "CloudPulse-Agent/1.0",
    }

    consecutive_errors = 0

    with httpx.Client(base_url=clean_url, timeout=10.0, headers=headers) as client:
        while True:
            try:
                metrics = collect_metrics()
                resp = client.post("/api/metrics", json=metrics)
                
                if resp.status_code == 200:
                    consecutive_errors = 0
                    data = resp.json()
                    alert_flag = " [ALERT]" if data.get("alert_triggered") else ""
                    disk_str = f"Disk {metrics.get('disk_usage', 0):4.1f}% | " if "disk_usage" in metrics else ""
                    
                    print(
                        f"[{time.strftime('%H:%M:%S')}] "
                        f"CPU {metrics['cpu_usage']:5.1f}% | "
                        f"RAM {metrics['ram_usage']:5.1f}% | "
                        f"{disk_str}"
                        f"Net {metrics['network_traffic']:6.2f} MB"
                        f" [200 OK]{alert_flag}"
                    )
                elif resp.status_code == 401:
                    print(f"[{time.strftime('%H:%M:%S')}] [401 UNAUTHORIZED] Ingestion token '{masked_token}' rejected by backend. Please verify your token.")
                elif resp.status_code == 404:
                    print(f"[{time.strftime('%H:%M:%S')}] [404 NOT FOUND] Server associated with this token was not found or has been terminated.")
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] [HTTP {resp.status_code}] {resp.text}")

            except httpx.ConnectError:
                consecutive_errors += 1
                if consecutive_errors == 1 or consecutive_errors % 6 == 0:
                    print(f"[{time.strftime('%H:%M:%S')}] [CONNECT ERROR] Cannot reach CloudPulse backend at {clean_url}. Retrying...")
            except httpx.TimeoutException:
                print(f"[{time.strftime('%H:%M:%S')}] [TIMEOUT] Request to {clean_url} timed out. Retrying...")
            except Exception as exc:
                print(f"[{time.strftime('%H:%M:%S')}] [ERROR] Unexpected exception: {exc}")

            time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="CloudPulse AI Telemetry Agent",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("CLOUDPULSE_TOKEN"),
        help="Server node ingestion bearer token (required or via CLOUDPULSE_TOKEN env)",
    )
    parser.add_argument(
        "--url",
        "--api-url",
        dest="api_url",
        default=os.environ.get("CLOUDPULSE_API_URL", "http://localhost:8000"),
        help="FastAPI backend URL",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("CLOUDPULSE_INTERVAL", "5")),
        help="Metrics collection interval in seconds",
    )
    args = parser.parse_args()

    if not args.token:
        parser.error("--token is required (or set CLOUDPULSE_TOKEN environment variable).")

    try:
        run_agent(token=args.token.strip(), api_url=args.api_url.strip(), interval=max(1, args.interval))
    except KeyboardInterrupt:
        print("\n[INFO] Telemetry agent shutdown requested. Exiting cleanly.")
        sys.exit(0)


if __name__ == "__main__":
    main()
