"""
Algo Lab — Network Connectivity Watchdog & Disconnection Guard.
Monitors WAN health, handles network dropouts gracefully, and triggers recovery reconciliation.
"""

import os
import sys
import socket
import time
from typing import Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from apps.api.core.logging import get_logger

logger = get_logger("NetworkConnectivityGuard")


class NetworkConnectivityGuard:
    """
    Watches network health, prevents crash loops during outages,
    and coordinates gap audits upon reconnection.
    """

    def __init__(
        self,
        probe_host: str = "8.8.8.8",
        probe_port: int = 53,
        timeout_sec: float = 2.0,
    ):
        self.probe_host = probe_host
        self.probe_port = probe_port
        self.timeout_sec = timeout_sec
        self.is_connected = True
        self.disconnected_since = None
        self.consecutive_failures = 0

    def probe(self) -> Tuple[bool, bool, float]:
        """
        Probes internet connectivity via low-latency TCP connect.
        Returns:
            Tuple[is_connected, state_changed, outage_duration_seconds]
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout_sec)
            sock.connect((self.probe_host, self.probe_port))
            sock.close()

            # Connection Successful
            if not self.is_connected:
                outage_duration = time.time() - (self.disconnected_since or time.time())
                self.is_connected = True
                self.disconnected_since = None
                self.consecutive_failures = 0
                logger.info(f"[NETWORK RECOVERED] WAN connectivity restored after {outage_duration:.1f}s.")
                return True, True, outage_duration

            self.consecutive_failures = 0
            return True, False, 0.0

        except (socket.error, OSError):
            self.consecutive_failures += 1
            if self.is_connected:
                self.is_connected = False
                self.disconnected_since = time.time()
                logger.warning("[NETWORK DROPPED] Internet connection lost. Entering defensive standby mode.")
                return False, True, 0.0

            outage_duration = time.time() - (self.disconnected_since or time.time())
            return False, False, outage_duration


if __name__ == "__main__":
    guard = NetworkConnectivityGuard()
    connected, changed, duration = guard.probe()
    print(f"NetworkConnectivityGuard Probe: Connected={connected}, Changed={changed}, Duration={duration}s")
