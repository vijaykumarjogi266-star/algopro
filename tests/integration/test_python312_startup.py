"""Regression tests for Python 3.12 startup, explicit typing resolution, and daemon import safety.

Tests:
T01: test_security_and_daemon_modules_import_on_python312
T02: test_annotation_types_resolve
T03: test_daemon_import_has_no_process_side_effects
T04: test_clean_install_service_imports
"""

import os
import signal
import subprocess
import sys
import typing
import pytest


def test_security_and_daemon_modules_import_on_python312():
    """T01: Fresh Python subprocess importing API main, breaker, orchestrator, daemon, and services."""
    env = dict(os.environ)
    env["ENVIRONMENT"] = "development"
    env["ALGO_LAB_API_KEY"] = "dev-test-key-minimum-32-chars-long-12345"
    env["CIRCUIT_BREAKER_REARM_SECRET"] = "dev-rearm-secret-minimum-32-chars-12345"
    env["CIRCUIT_BREAKER_STATE_KEY"] = "dev-state-key-minimum-32-chars-123456"
    env["BROKER_CREDENTIAL_ENCRYPTION_KEY"] = "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE="

    code = """
import sys
import run_live_paper_daemon
from services.execution_gateway.circuit_breaker import CircuitBreakerEngine
from services.paper_engine.autonomous_orchestrator import AutonomousSentinel
from apps.api.main import app

print("IMPORT_SUCCESS")
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Import failed with stderr:\n{proc.stderr}"
    assert "IMPORT_SUCCESS" in proc.stdout


def test_annotation_types_resolve():
    """T02: typing.get_type_hints resolves all annotations without NameError."""
    from services.execution_gateway.circuit_breaker import CircuitBreakerEngine
    from services.paper_engine.autonomous_orchestrator import AutonomousSentinel
    from services.execution_gateway.contracts import OrderPayload

    # CircuitBreakerEngine.validate_order must resolve OrderPayload
    hints_cb = typing.get_type_hints(CircuitBreakerEngine.validate_order)
    assert hints_cb.get("order") is OrderPayload, f"Expected OrderPayload, got {hints_cb.get('order')}"

    # AutonomousSentinel.execute_eod_reconciliation_and_tearsheet must resolve Tuple
    hints_orch = typing.get_type_hints(AutonomousSentinel.execute_eod_reconciliation_and_tearsheet)
    assert "return" in hints_orch
    assert typing.get_origin(hints_orch["return"]) is tuple or hasattr(hints_orch["return"], "__origin__")


def test_daemon_import_has_no_process_side_effects():
    """T03: Importing run_live_paper_daemon must not register signals, make network calls, or exit."""
    code = """
import signal
import socket
import sys
from unittest.mock import patch

# Record initial signal handlers
sigint_before = signal.getsignal(signal.SIGINT)
sigterm_before = signal.getsignal(signal.SIGTERM)

# Instrument network and sys.exit hooks
network_called = False
orig_connect = socket.socket.connect
def guard_connect(self, *args, **kwargs):
    global network_called
    network_called = True
    raise RuntimeError("Unexpected network call during module import")

with patch.object(socket.socket, "connect", guard_connect):
    import run_live_paper_daemon

# Assert signal handlers unchanged
sigint_after = signal.getsignal(signal.SIGINT)
sigterm_after = signal.getsignal(signal.SIGTERM)

assert sigint_before == sigint_after, "SIGINT handler was modified during import"
assert sigterm_before == sigterm_after, "SIGTERM handler was modified during import"
assert not network_called, "Network call was attempted during import"

print("SAFE_IMPORT_VERIFIED")
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Daemon import had side effects:\n{proc.stderr}"
    assert "SAFE_IMPORT_VERIFIED" in proc.stdout


def test_clean_install_service_imports():
    """T04: Verify all underscore-named and dash-named service packages import properly."""
    packages = [
        "services.backtest_engine",
        "services.paper_engine",
        "services.risk_engine",
        "services.market_data",
        "services.derivatives_engine",
        "services.execution_gateway",
        "services.observability",
    ]
    for pkg in packages:
        mod = __import__(pkg, fromlist=["*"])
        assert mod is not None, f"Failed to import {pkg}"
