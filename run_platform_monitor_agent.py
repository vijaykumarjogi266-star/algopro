#!/usr/bin/env python3
"""Run Platform Sentinel & Monitoring Agent CLI.

Usage:
    python3 run_platform_monitor_agent.py --check-once
    python3 run_platform_monitor_agent.py --daemon --interval 60
"""

import argparse
import json
import sys
import time

from services.monitoring.platform_monitor_agent import PlatformMonitorAgent


def main():
    parser = argparse.ArgumentParser(description="Algo Lab Platform Sentinel & Monitoring Agent")
    parser.add_argument("--check-once", action="store_true", help="Run diagnostic probe once and exit")
    parser.add_argument("--daemon", action="store_true", help="Run continuous monitoring loop")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds (default: 60)")
    args = parser.parse_args()

    agent = PlatformMonitorAgent()

    if args.daemon:
        print(f"[*] Starting Platform Monitor Agent daemon (interval: {args.interval}s)...")
        try:
            while True:
                report = agent.run_full_diagnostic()
                status = "HEALTHY" if report.overall_healthy else "CRITICAL / DEGRADED"
                print(f"[{report.timestamp.isoformat()}] Platform Status: {status}")
                for check in report.checks:
                    icon = "✓" if check.passed else "✗"
                    print(f"  {icon} [{check.severity}] {check.name}: {check.message}")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[*] Platform Monitor Agent daemon stopped cleanly.")
            sys.exit(0)
    else:
        report = agent.run_full_diagnostic()
        print(json.dumps(report.model_dump(), indent=2, default=str))
        sys.exit(0 if report.overall_healthy else 1)


if __name__ == "__main__":
    main()
